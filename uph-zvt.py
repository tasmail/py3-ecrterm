#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
script to execute a payment process.
"""
from ecrterm.ecr import ECR, ecr_log
from ecrterm.packets.base_packets import Registration
import sys

URL='socket://IP_ADRESSE:20007'
PASSWORD='111111'

def printer(lines_of_text):
    for line in lines_of_text:
        print(line)


if __name__ == '__main__':

    if (len(sys.argv) != 2):
        print("Bitte den Betrag in cent als Parameter übergeben")
    else:
        betrag = sys.argv[1]
        e = ECR(device=URL , password=PASSWORD )
        # reenable logging:
        #MH e.transport.slog = ecr_log
        #print(e.detect_pt())
        if e.detect_pt():
            #print('after detect. now: register...')
            e.register(config_byte=Registration.generate_config(
                ecr_prints_receipt=True,        # MH
                ecr_prints_admin_receipt=False,
                ecr_controls_admin=True,
                ecr_controls_payment=True))
            #print ('waiting...')
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

            if e.payment(amount_cent=betrag):
                #print('------------last_printout:------------------')
                printer(e.last_printout())
                e.wait_for_status()
                e.show_text(
                    lines=[' :-) ', ' ', 'Zahlung erfolgt'], beeps=1)
                print('SUCCESS')
            else:
                e.wait_for_status()
                e.show_text(
                    lines=[' :-( ', ' ', 'Vorgang abgebrochen'],
                    beeps=2)
                print('FAILED')
