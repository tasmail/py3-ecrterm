#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Example script to demonstrate a payment process.
"""
from ecrterm.ecr import ECR, ecr_log
from ecrterm.packets.base_packets import Registration


def printer(lines_of_text):
    for line in lines_of_text:
        print(line)


if __name__ == '__main__':
    e = ECR(device='socket://192.168.1.113:5577', password='111111')
    # e = ECR(device='socket://192.168.1.35:20007', password='123456')
    # reenable logging:
    e.transport.slog = ecr_log
    print(e.detect_pt())
    if e.detect_pt():
        e.register(config_byte=Registration.generate_config(
            ecr_prints_receipt=False,
            ecr_prints_admin_receipt=False),
            tlv=0xD3)

        e.wait_for_status()
        status = e.status()
        if status:
            print('Status code of PT is %s' % status)
            # laut doku sollte 0x9c bedeuten, ein tagesabschluss erfolgt
            # bis jetzt unklar ob er es von selbst ausführt.

            if status == 0x9c:
                print('End Of Day')
                e.end_of_day()
                # last_printout() would work too:
                printer(e.daylog)
            else:
                print('Unknown Status Code: %s' % status)
                # status == 0xDC for ReadCard (06 C0) -> Karte drin.
                # 0x9c karte draussen.

        test_lines = [
            ('       Euro Palace    ', 0),
            ('  Peter-Sander-Strasse 39', 0),
            ('    55252 Mainz-Kastel', 0),
            (' ', 0),
            (' USt-ID Nr.: DE 311004438', 0),
            ('      ', 0),
            ('     19.04.2022 13:28', 0),
            ('', 0),
            ('Red Bull "Blue Edition"', 0),
            ('1x4,50         4,50 EUR', 0),
            ('', 0),
            ('------------------------------', 0),
            ('', 0),
            ('Gesamtsumme:         4,50 EUR', 0),
            ('19% Umsatzsteuer:    0,72 EUR', 0),
            ('Bezahlt:             4,50 EUR', 0),
            ('Rückgabe:            0,00 EUR', 0),
        ] + [('', 0)] * 5

        e.print_text(lines=test_lines)

        if e.payment(amount_cent=1):
            printer(e.last_printout())
            e.wait_for_status()
            e.show_text(
                lines=['Auf Wiedersehen!', ' ', 'Zahlung erfolgt'], beeps=1)
        else:
            e.wait_for_status()
            e.show_text(
               lines=['Auf Wiedersehen!', ' ', 'Vorgang abgebrochen'],
               beeps=2)
