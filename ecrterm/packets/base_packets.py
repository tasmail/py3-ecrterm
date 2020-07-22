import datetime
import struct
from typing import Dict

from .apdu import CommandAPDU
from .fields import *
from .types import *
from .text_encoding import ZVT_7BIT_CHARACTER_SET


class Packet(CommandAPDU):
    wait_for_completion = False
    completion = None
    response_listener = None

    def _handle_unknown_response(self, response, tm):
        print('Unknown packet response %s' % response)
        tm.send_received()
        return False

    def _handle_super_response(self, response, tm):
        """
        allows a packet to handle all responses in a transmission by itself.
        returns a tuple:
        - first is if handle_super_response has an answer.
        - second is the handle_response answer.
        if first is False, second is omitted, and packet is still cared
        by handle_response itself.

        Standard: saves "completion" packets on self, does not tell
        anybody.
        """
        if isinstance(response, Completion) or isinstance(response, Abort):
            # some sort of completion.
            self.completion = response
        return False, False

    def register_response_listener(self, listener):
        self.response_listener = listener

    def handle_response(self, response, tm) -> bool:
        """
        Handle a response for a certain packet type, return `True` if
        the ECR should become master, `False` otherwise.
        """
        ihandle, istatus = self._handle_super_response(response, tm)
        if ihandle:
            return istatus
        if isinstance(response, PacketReceived):
            # just continue.
            return not self.wait_for_completion
        elif isinstance(response, PacketReceivedError):
            return True
        elif isinstance(response, Completion):
            tm.send_received()
            return True
        elif isinstance(response, Abort):
            # print "Abort. CODE: %s" % response.error_code
            tm.send_received()
            return True
        elif isinstance(response, StatusInformation):
            # @todo: status infomation packets
            tm.send_received()
            if self.response_listener:
                self.response_listener(response)
            return False
        elif isinstance(response, IntermediateStatusInformation):
            # @todo: extended status information packets.
            tm.send_received()
            if self.response_listener:
                self.response_listener(response)
            return False
        elif isinstance(response, PrintLine):
            tm.send_received()
            if self.response_listener:
                self.response_listener(response)
            return False
        elif isinstance(response, PrintTextBlock):
            tm.send_received()
            if self.response_listener:
                self.response_listener(response)
            return False
        else:
            return self._handle_unknown_response(response, tm)


class CommandWithPassword(Packet):
    CMD_CLASS = 0x06

    password = BCDField(length=3)


class Registration(CommandWithPassword):
    """
    06 00
    Registration.
    arguments: password, cc, config_byte
    bitmaps: service_byte
    """
    CMD_CLASS = 0x06
    CMD_INSTR = 0x00
    wait_for_completion = True

    config_byte = FlagByteField(data_type=ConfigByte)
    cc = BCDIntField(data_type=CurrencyCode, length=2, required=False)


class Kassenbericht(CommandWithPassword):
    """A cardcomplete packet?"""
    CMD_CLASS = 0x0f
    CMD_INSTR = 0x10
    wait_for_completion = True


class EndOfDay(CommandWithPassword):
    CMD_INSTR = 0x50
    wait_for_completion = True

class LogOff(Packet):
    """06 02 Log Off"""
    CMD_CLASS = 0x06
    CMD_INSTR = 0x02


class Initialisation(CommandWithPassword):
    """
    06 93
    With this command the ECR forces the PT to execute a
    Network-Initialization.
    """
    CMD_INSTR = 0x93
    wait_for_completion = True


class DisplayText(Packet):
    """
    06 E0
    chapters: bzt 3.2.26, pt 2.24
    Note: only line 1-4 can be used by BZT.
    bitmap: F0, duration, 0 = forever
    F1-F8: text, 7bit ascii
    """
    CMD_CLASS = 0x06
    CMD_INSTR = 0xe0

    ALLOWED_BITMAPS = ['display_duration', 'line1', 'line2', 'line3', 'line4', 'line5', 'line6', 'line7', 'line8',
                       'beeps']


class DisplayTextIntInput(Packet):
    """
    06 E2
    text output with numerical input.
    """
    CMD_CLASS = 0x06
    CMD_INSTR = 0xe2


class AbortCommand(Packet):
    """
    06 B0
    * Sent by ECR to abort a running transaction in the PT
    * Allowed without master rights, but only for some commands
    """
    CMD_CLASS = 0x06
    CMD_INSTR = 0xb0


class Completion(Packet):
    """
    06 0F
    * Sent to the ECR to signal him getting master rights back.
    * PT>ECR
    """
    CMD_CLASS = 0x06
    CMD_INSTR = 0x0f

    # The sw_version field is optional but first. It will be sent or not depending on
    # a bit in the previous Enquiry, which the parser doesn't know about. It's technically
    # impossible to parse this protocol properly. We'll try anyway.
    #
    # Observe that the sw_version field is of type LLLVar, so will always start with bytes
    # of the form FxFyFz. terminal_status is 1 byte and arbitrary (and might match Fx), but
    # the only allowed bitmap is 06 (tlv), which will *not* match.
    # So in case a sw_version field is present, the LLLStringField parser will reliably
    # remove it, and if it's not present it will reliably signal a parsing error.
    # Setting ignore_parse_error to True will suppress that parse error and continue with
    # the rest of the packet.

    sw_version = LLLStringField(required=False, ignore_parse_error=True, character_set=ZVT_7BIT_CHARACTER_SET)
    terminal_status = ByteField(required=False, ignore_parse_error=True)

    ALLOWED_BITMAPS = ['tlv', 'status_byte', 'tid', 'currency_code']


class Abort(Packet):
    """
    06 1E
    usually length 1, it can have data, which represents a one byte error
    code
    """
    CMD_CLASS = 0x06
    CMD_INSTR = 0x1e

    result_code = ByteField()
    # FIXME error_code


class StatusInformation(Packet):
    """
    04 0F
    this one is important so i mark it here.
    """
    CMD_CLASS = 0x04
    CMD_INSTR = 0x0f

    # FIXME Check and test. Better yet: Make totals a Container
    def get_end_of_day_information(self):
        """
        if this status information is sent in an end of day cycle,
        it contains the end of day information, making it a type of
        subpacket of itself.

        @returns: a dictionary holding end-of-day information.

        - returns an empty dictionary if there is no total amount
        - returns total amount at least in key 'amount'
        - tries to decipher credit card data into following format:
          number-<creditcard>, turnover-<creditcard>
          creditcard being [ec-card, jcb, eurocard, amex, visa, diners,
          remaining]
        - receipt-number-start, receipt-number-end contain the range of
          receipts
        """
        ret = {}
        # create a dictionary of bitmaps:
        bdict = self.as_dict()
        # at least amount should be present:
        if 'amount' not in bdict.keys():
            return {}
        else:
            ret = {'amount': bdict['amount'], }
        # bitmap 0x60 (totals) contains the required information.
        # another bitmap (amount) holds the amount

        ## FIXME Parsing of totals in the parser
        return ret

        if 'totals' not in bdict.keys():
            # this packet holds no detail information but an amount.
            return ret
        totals = bdict['totals']
        totals_list = totals.value()
        # totals_list = str(bdict['totals'])
        # now we build our real data our of it.

        # rebuild date and time.
        my_time = None
        my_date = None
        if 'time' in bdict.keys():
            # print bdict['time'].value()
            mt = str(bdict['time'].value())
            my_time = datetime.time(
                hour=int(mt[0:2]), minute=int(mt[2:4]), second=int(mt[4:6]))
        if 'date_day' in bdict.keys():
            # print bdict['date'].value()
            md = str(bdict['date_day'].value())
            my_date = datetime.date(
                year=datetime.datetime.now().year, month=int(md[0:2]),
                day=int(md[2:4]))
        ret = {
            'receipt-number-start':
                BCD.as_int(BCD.decode_bcd(totals_list[0:2])),
            'receipt-number-end':
                BCD.as_int(BCD.decode_bcd(totals_list[2:4])),
            'number-ec-card': bs2hl(totals_list[4])[0],
            'turnover-ec-card':
                BCD.as_int(BCD.decode_bcd(totals_list[5:5 + 6])),
            'number-jcb': bs2hl(totals_list[11])[0],
            'turnover-jcb': BCD.as_int(BCD.decode_bcd(totals_list[12:12 + 6])),
            'number-eurocard': bs2hl(totals_list[18])[0],
            'turnover-eurocard':
                BCD.as_int(BCD.decode_bcd(totals_list[19:19 + 6])),
            'number-amex': bs2hl(totals_list[25])[0],
            'turnover-amex':
                BCD.as_int(BCD.decode_bcd(totals_list[26:26 + 6])),
            'number-visa': bs2hl(totals_list[32])[0],
            'turnover-visa':
                BCD.as_int(BCD.decode_bcd(totals_list[33:33 + 6])),
            'number-diners': bs2hl(totals_list[39])[0],
            'turnover-diners':
                BCD.as_int(BCD.decode_bcd(totals_list[40:40 + 6])),
            'number-remaining': bs2hl(totals_list[46])[0],
            'turnover-remaining':
                BCD.as_int(BCD.decode_bcd(totals_list[47:47 + 6])),
            'amount': int(bdict['amount'].value()),
            'turnover-amount': int(bdict['amount'].value()),
            'date': my_date,
            'time': my_time,
            'number-total': 0,
        }
        # time holds simply HHMMSS (BCD)
        # date holds simply mmdd (BCD)

        # adding a formatted version
        tn = 0
        float_version = {}
        for key, value in ret.items():
            if key.startswith('turnover-'):
                key_id = key.replace('turnover-', '')
                # add a key with a formatted representation.
                v = float(value) / 100.0
                float_version['float-%s' % key_id] = v
            elif key.startswith('number-'):
                # add total numbers.
                tn += int(value)
        ret['number-total'] = tn
        ret.update(float_version)
        return ret


class IntermediateStatusInformation(Packet):
    """
    04 FF
    this one is important so i mark it here.
    """
    CMD_CLASS = 0x04
    CMD_INSTR = 0xff

    intermediate_status = ByteField()  # FIXME enum
    timeout = ByteField(required=False)


class PacketReceived(Packet):
    """
    80 00
    most used packet ever: Packet Received Successfully.
    PT<->ECR
    """
    CMD_CLASS = 0x80
    CMD_INSTR = 0x00


class PacketReceivedError(Packet):
    """
    84 XX
    Some error occured receiving the packet.
    """
    CMD_CLASS = 0x84
    CMD_INSTR = Ellipsis  # FIXME Enum

    # FIXME Test serialization


class Authorisation(Packet):
    """
    06 01
    If you want to authorize a transaction, this is the packet you need
    to start with. Also for reading card data in general.
    """
    CMD_CLASS = 0x06
    CMD_INSTR = 0x01
    wait_for_completion = True

    ALLOWED_BITMAPS = [
        'amount', 'currency_code', 'status_byte', 'track_1', 'card_expire',
        'card_number', 'track_2', 'track_3', 'timeout', 'max_status_infos',
        'pump_nr', 'cvv', 'additional', 'card_type', 'tlv']


class PrintLine(Packet):
    """
    06 D1
    Usually sent by PT to ECR telling him to print a line.
    Needed for diagnosis.
    """
    CMD_CLASS = 0x06
    CMD_INSTR = 0xd1

    attribute = ByteField()
    text = StringField(required=False)

    # FIXME Code and tests for special behaviour


class PrintTextBlock(Packet):
    """
    06 D3
    Same as Printline but for a textblock.
    However, uses TLV so not used in basic implementation.
    """
    CMD_CLASS = 0x06
    CMD_INSTR = 0xd3

    REQUIRED_BITMAPS = [
        'tlv'
    ]


class Diagnosis(Packet):
    """
    06 70
    """
    CMD_CLASS = 0x06
    CMD_INSTR = 0x70
    wait_for_completion = True

    def _handle_response(self, response, tm):
        if isinstance(response, PrintLine):
            print(response._data)
            tm.send_received()
            return False


class ActivateCardReader(Packet):
    """
    08 50
    Dieses Paket ist im CardComplete nicht implementiert.
    """
    CMD_CLASS = 0x08
    CMD_INSTR = 0x50

    activate = ByteField()


class ReadCard(Packet):
    """
    06 C0
    !!! For new implementations the ECR should not send the command
    Read-Card with infinite time-out,
    but rather should use command Status-Readout until a card is
    inserted. Following this the card can be read.
    !!! Cardcomplete does not use card_type or any other stuff here.
    """
    CMD_CLASS = 0x06
    CMD_INSTR = 0xc0
    wait_for_completion = True  # note, we do not wait for completion actually.

    timeout = ByteField()
    ALLOWED_BITMAPS = [
        'status_byte',
        'dialog_control',
        'tlv',
    ]


class CloseCardSession(CommandAPDU):
    CMD_CLASS = 0x06
    CMD_INSTR = 0xC5
    wait_for_completion = False


class ResetTerminal(CommandAPDU):
    """
    06 18
    works.
    """
    CMD_CLASS = 0x06
    CMD_INSTR = 0x18
    wait_for_completion = True


class StatusEnquiry(CommandWithPassword):
    """
    05 01
    """
    CMD_CLASS = 0x05
    CMD_INSTR = 0x01
    wait_for_completion = True


class ChangePTConfiguration(Packet):
    CMD_CLASS = 0x08
    CMD_INSTR = 0x13
    wait_for_completion = True

    ALLOWED_BITMAPS = ['tlv']


class SetTerminalID(CommandWithPassword):
    CMD_CLASS = 0x06
    CMD_INSTR = 0x1B
    wait_for_completion = True


class RequestFile(Packet):
    CMD_CLASS = 0x04
    CMD_INSTR = 0x0c


class WriteFileBase(CommandWithPassword):
    CMD_CLASS = 0x08
    CMD_INSTR = 0x14
    wait_for_completion = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for k, v in self.get_files_().items():
            self.tlv.append_('x2d', {'x1d': bytes([k]), 'x1f00': struct.pack('!L', v)}, overwrite=False)

    def get_files_(self) -> Dict[int, int]:
        raise NotImplementedError

    def get_file_content_(self, file_id: int, offset: int, length: Optional[int] = None):
        raise NotImplementedError

    def _handle_super_response(self, response, tm):
        if isinstance(response, RequestFile):
            pkt = self.get_answer_(response)
            if pkt is not None:
                # FIXME There should be an API for this  (basically currently a copy of "send_received()")
                tm.history += [(False, pkt), ]
                from ecrterm.transmission._transmission import logger
                logger.debug("> %r", pkt)
                tm.transport.send(pkt.serialize(), no_wait=True)
                return True, False
        return super()._handle_super_response(response, tm)

    def get_answer_(self, cmd):
        if isinstance(cmd, RequestFile):
            # FIXME Maybe more fancy way to select file
            # FIXME Ensure necessary tags are present
            # FIXME Find out maximum read length
            readlength = 65000
            file_id = cmd.tlv.x2d.x1d
            offset = cmd.tlv.x2d.x1e
            data = self.get_file_content_(file_id, offset, readlength)
            return PacketReceived(tlv={0x2d: {
                0x1d: bytes([file_id]),
                0x1e: struct.pack('!L', offset),
                0x1c: data,
            }})


class WriteFiles(WriteFileBase):
    def __init__(self, files: Dict[int, bytes] = None, *args, **kwargs):
        self._files = files
        super().__init__(*args, **kwargs)

    def get_files_(self) -> Dict[int, int]:
        return {k: len(v) for (k, v) in self._files.items()}

    def get_file_content_(self, file_id: int, offset: int, length: Optional[int] = None):
        if length is not None:
            return self._files[file_id][offset:(offset+length)]
        else:
            return self._files[file_id][offset:]

    @classmethod
    def can_parse(cls, data: Union[bytes, List[int]]) -> bool:
        return False
