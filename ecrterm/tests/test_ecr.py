"""
Tests for the high level ECR api without a connected terminal.
"""
from unittest import TestCase, main

from ecrterm.ecr import ECR
from ecrterm.packets.base_packets import Diagnosis
from ecrterm.transmission.signals import TRANSMIT_OK


class RecordingECR(ECR):
    """ECR which records transmitted packets instead of sending them."""

    def __init__(self):
        self.sent = []

    def transmit(self, packet):
        self.sent.append(packet)
        return TRANSMIT_OK


class TestECRDiagnosis(TestCase):

    def test_diagnosis_sends_requested_type(self):
        ecr = RecordingECR()
        result = ecr.diagnosis(Diagnosis.TYPE_EMV_CONFIGURATION)
        self.assertEqual(TRANSMIT_OK, result)
        self.assertEqual(1, len(ecr.sent))
        self.assertIsInstance(ecr.sent[0], Diagnosis)
        self.assertEqual(
            Diagnosis.TYPE_EMV_CONFIGURATION, ecr.sent[0].diagnosis_type)

    def test_diagnosis_without_type_sends_empty_packet(self):
        ecr = RecordingECR()
        ecr.diagnosis()
        self.assertEqual([0x06, 0x70, 0x00], ecr.sent[0].to_list())

    def test_diagnosis_registers_listener(self):
        ecr = RecordingECR()

        def listener(response):
            pass

        ecr.diagnosis(listener=listener)
        self.assertIs(listener, ecr.sent[0].response_listener)


if __name__ == '__main__':
    main()
