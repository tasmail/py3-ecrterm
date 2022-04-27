"""Classes and Functions which deal with the APDU Layer."""

from logging import debug

from six.moves import range

from ecrterm.conv import toBytes
from ecrterm.exceptions import NotEnoughData
from ecrterm.packets.bitmaps import BITMAPS_ARGS
from ecrterm.packets.bmp import BMP, int_word_split
from ecrterm.utils import is_stringlike


class _PacketRegister:
    """
    All Packets come into this register. Singleton for each Protocol.
    """
    # Currencies
    CC_EUR = [0x09, 0x78]
    # Command Classes
    CMD_STD = 0x6  # all standard commands, mostly ecr to pt
    CMD_SERVICE = 0x8  # commands mostly for service. mostly ecr to pt.
    CMD_PT = 0x4  # commands from pt to ecr.
    CMD_STATUS = 0x5  # only seen in 05 01 : status inquiry.
    # from pt to ecr only:
    CMD_RESP_OK = 0x80  # work done
    CMD_RESP_ERROR = 0x84  # work had errors

    def __init__(self):
        self.packets = {}

    def register(self, packet_class):
        if packet_class.cmd_class:
            # cmd_class is needed to be registered.
            if packet_class.cmd_instr is not None:
                # this packet is a specific tuple of instructions.
                # it will be registered as such
                key_str = '%s_%s' % (
                    hex(packet_class.cmd_class), hex(packet_class.cmd_instr))
                # debug
                debug('Registered Class %s for Command Tuple ( %s, %s )'
                      % (str(packet_class),
                         hex(packet_class.cmd_class),
                         hex(packet_class.cmd_instr)))
            else:
                # this packet handles a variety of supercommands
                key_str = '%s' % hex(packet_class.cmd_class)
                # debug
                debug('Registered Class %s for Super Command Fallback ( %s )'
                      % (str(packet_class),
                         hex(packet_class.cmd_class)))
            self.packets[key_str] = packet_class

    def detect(self, datastream):
        def _convert(dt):
            for x in dt:
                if isinstance(x, int):
                    yield x
                    continue

                if isinstance(x, str):
                    yield ord(x)
                    continue

        datastream2 = list(_convert(datastream))
        cc, ci = datastream2[:2]
        return self.packets.get(
            '%s_%s' % (hex(cc), hex(ci)),
            self.packets.get('%s' % (hex(cc)), None))


Packets = _PacketRegister()


class APDUPacket(object):
    """
    Packet can be created by binary data or programmatically.
    Goal is to not save any binary data in the instance anymore.
    Translation from data to classes and vice versa should be fluent.
    """
    cmd_class = 0x6  # standard.
    cmd_instr = None
    allowed_bitmaps = None  # None=All, [] = None.
    fixed_arguments = []
    fixed_values = {}

    # Initializing
    def __init__(self, *args, **kwargs):
        num_fixed = len(self.fixed_arguments or [])
        num_given = len(args or [])
        fvalues = {}
        if self.fixed_values:
            fvalues.update(self.fixed_values)
        i = 0
        while (i < num_given) and (i < num_fixed):
            #
            fvalues[self.fixed_arguments[i]] = args[i]
            i += 1
        # the kwargs are the bitmaps.
        bitmaps = []
        for k, v in kwargs.items():
            if k in self.fixed_arguments:
                fvalues[k] = v
            else:
                key, klass, info = BITMAPS_ARGS.get(k, (None, None, None))
                if klass:
                    bmp = klass(v)
                    bmp._id = key
                    bmp._descr = info
                    bitmaps += [bmp]
        self.fixed_values = fvalues
        self.args = args or []
        self.kwargs = kwargs or {}
        self.bitmaps = bitmaps

    def validate(self):
        # look thru all arguments: all needed fixed arguments here?
        # look thru all bitmaps: all bitmaps allowed?
        return True

    def handle_response(self, response, transmitter):
        # handle response overwrite
        pass

    #############################################
    # Serializing ###############################
    #############################################
    @classmethod
    def data_length(cls, data):
        """
        if data length l < 255: length is 1 byte.
        if data length 254 < l < 65535: length is 3 bytes.
        L = 0xFF -> following two bytes are length.
        """
        data_len = len(data)
        if data_len > 254:
            if data_len > 65535:
                raise NotImplementedError(
                    "APDU Data length cannot be bigger than 2 bytes.")
            return [0xFF, ] + int_word_split(data_len)
        return [data_len]

    def enrich_fixed(self):
        """
        fixed arguments should be enriched here into the datastream.
        as to speak: serialized.

        by default, it will try to serialize fixed_arguments from fixed_values
        """
        self.validate()
        ds = []
        if self.fixed_arguments and self.fixed_values:
            # we have fixed arguments here
            for i in range(len(self.fixed_arguments)):
                val = self.fixed_values.get(self.fixed_arguments[i], None)
                if val:
                    if is_stringlike(val):
                        val = toBytes(val)
                    elif isinstance(val, list):
                        pass
                    else:
                        val = [val, ]
                    # now just save it into ds
                    ds += val
        return ds

    def introspect_fixed(self):
        """Return a description of your fixed data."""
        return self.fixed_values

    def get_data_raw(self):
        # getting the data of a packet means it is serialized into bytes.
        data = []
        # first, lets get the enriched fixed arguments:
        data += self.enrich_fixed()
        # now serialise all our bitmaps.
        # try to order our bitmaps after allowed_bitmaps maybe?
        for bitmap in self.bitmaps:
            # is bitmap allowed?
            # if y,
            data += bitmap.dump()
        # last: insert the length
        return data

    def get_data(self):
        data = self.get_data_raw()
        return self.data_length(data) + data

    def to_list(self):
        return [self.cmd_class, self.cmd_instr or 0] + self.data

    def to_bytes(self):
        return ''.join(list(map(chr, self.to_list())))

    #############################################
    # Parsing ###################################
    #############################################
    def consume_fixed(self, data, length):
        """
        Overwrite this Function for your Packet to consume fixed
        arguments not represented by bitmaps.
        This data usually comes before any bitmaps are present
        and each packet has to know for itself, how to handle them.

        data is the whole packet data after the length part

        length is the given data-length coded into the packet.
        """
        # consume all fixed arguments from data here.
        # this might be very different from packet to packet.
        # if you use fixed_values as store, dont forget to save binary data.
        return data

    def set_data(self, blob):
        # setting the data of a packet means, it is parsed actually.
        # note: data does NOT containt cmd_class, cmd_instr anymore!
        # however, it DOES contain the LENGTH
        # now we introspect data
        pos = 0
        bitmaps = []
        if blob[pos] == 0xff:
            # length field is next two bytes.
            # @todo: could be wrong:
            length = (blob[pos + 2] << 8) + blob[pos + 1]
            pos += 2  # consume 2 bytes.
        else:
            length = blob[pos]
        pos += 1  # we move one byte further in all cases.
        # now we should read our data ahead to length.
        # look ahead if we have enough data.
        if len(blob) >= pos + length:
            data = blob[pos:pos + length]
        else:
            raise NotEnoughData('Not enough Data to create the packet data.')
        # step 1: fixed arguments.
        # if this packet has some fixed arguments, they have to be
        # parsed first.
        data = self.consume_fixed(data, length)
        # step 2: bitmaps.
        while data:
            bmp, data = BMP.read_stream(data)
            bitmaps += [bmp]
        self.bitmaps = bitmaps
    data = property(get_data, set_data)

    @classmethod
    def parse(cls, blob=''):
        if is_stringlike(blob):
            # lets convert our string into a bytelist.
            blob = toBytes(blob)
        if type(blob) is list:
            # allright.
            # first we detect our packetclass
            PacketClass = Packets.detect(blob[:2])
            if PacketClass:
                instance = PacketClass()
                # fix for multipackets:
                if instance.cmd_instr is None:
                    instance.cmd_instr = blob[1]
                instance.data = blob[2:]
                if not instance.validate():
                    debug('Validation Error')
                return instance
            else:
                debug('Unknown Packet')
