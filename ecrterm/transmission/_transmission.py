"""
Transmission Basics.
@author g4b
"""
import time

from ecrterm.exceptions import TransmissionException, TransportLayerException, TransportTimeoutException
from ecrterm.packets.base_packets import PacketReceived, AbortCommand, Authorisation, IntermediateStatusInformation
from ecrterm.transmission.signals import TIMEOUT_T4_DEFAULT, TRANSMIT_OK, TRANSMIT_TIMEOUT


class Transmission(object):
    """
    A Transmission Object represents an open connection between ECR and
    PT. It regulates the flow of packets, and uses a Transport to send
    its data. The default Transport to use is the serial transport.
    """
    actual_timeout = TIMEOUT_T4_DEFAULT
    last = None

    def __init__(self, transport):
        self.transport = transport
        self.is_master = True
        self.is_waiting = False
        self.last = None  # saves last sent master
        self.log_list = []
        self.history = []
        self.last_history = []
        self._is_abort_command_requested = False

    def log_response(self, response):
        """
        Every response is saved into self.log_list. Hook this for live
        data.
        """
        self.log_list += [response]

    def send_received(self):
        """Send the "Packet Received" Packet."""
        packet = PacketReceived()
        self.history += [(False, packet), ]
        self.transport.send(packet, no_wait=True)

    def handle_packet_response(self, packet, response):
        """A shortcut for calling the handle_response of the packet."""
        return packet.handle_response(response, self)

    def _transmit(self, packet, history):
        """
        Transmit the packet, go into slave mode and wait until the whole
        sequence is finished.
        """
        if not self.is_master or self.is_waiting:
            raise TransmissionException(
                'Can\'t send until transmisson is ready')

        self._is_abort_command_requested = False
        self.is_master = False
        self.last = packet

        try:
            history += [(False, packet)]
            success, response = self.transport.send(packet)
            history += [(True, response)]
            is_payment = isinstance(packet, Authorisation)

            # we sent the packet.
            # now lets wait until we get master back.
            stopwatch = time.time()

            while not self.is_master:
                # First, handle the current response
                self.is_master = self.handle_packet_response(
                    self.last, response)

                if self.is_master:
                    break

                # Now check if abort should be sent BEFORE receiving next packet
                if is_payment and self._is_abort_command_requested:
                    print('Abort Was Requested.')
                    is_abort_allowed = False

                    # Check if the LAST RESPONSE we just handled was "insert card"
                    if isinstance(response, IntermediateStatusInformation) and response.is_insert_card_status():
                        is_abort_allowed = True

                    if is_abort_allowed:
                        print('Abort Is Allowed.')
                        try:
                            abort_packet = AbortCommand()
                            self.last = abort_packet
                            history += [(False, abort_packet)]
                            success, abort_response = self.transport.send(abort_packet)
                            history += [(True, abort_response)]

                            # CRITICAL: Update response to the abort response
                            response = abort_response

                            # Clear the flag
                            self._is_abort_command_requested = False

                            # Continue to top of loop to handle abort response
                            continue

                        except TransportLayerException:
                            # If we're already master, we can ignore this
                            if self.is_master:
                                return TRANSMIT_OK
                            raise
                        except Exception:
                            self._is_abort_command_requested = False
                            raise
                    else:
                        print('Abort IS NOT Allowed.')
                        self._is_abort_command_requested = False

                # Receive next packet
                try:
                    success, response = self.transport.receive(TRANSMIT_TIMEOUT)
                    history += [(True, response)]
                except TransportTimeoutException:
                    if (time.time() - stopwatch) >= self.actual_timeout:
                        raise
                    # Continue loop if timeout hasn't expired yet
                    continue
                except TransportLayerException:
                    # some kind of timeout.
                    # if we are already master, we can bravely ignore this.
                    if self.is_master:
                        return TRANSMIT_OK
                    raise

                if self.is_master and success:
                    # we actually have to handle a last packet
                    stay_master = self.handle_packet_response(
                        packet, response)
                    print('Is Master Read Ahead happened.')
                    self.is_master = stay_master

        except Exception:
            self.is_master = True
            self._is_abort_command_requested = False
            raise

        self.is_master = True
        return TRANSMIT_OK

    def request_abort_command(self):
        self._is_abort_command_requested = True

    def transmit(self, packet, history=None):
        # we create a new history:
        self.last_history = history or []
        try:
            ret = self._transmit(packet, self.last_history)
            self.history += self.last_history
            return ret
        except Exception:
            self.history += self.last_history
            raise
