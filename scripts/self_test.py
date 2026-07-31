#!/usr/bin/env python3
from parse_att import parse_page as parse_att
from parse_spk import parse_page as parse_spk
from parse_spk2 import parse_page as parse_spk2


def main():
    spk_html = '''<html><body>
    <div>№ свидетельства</div><div>05890263.2142-2025</div>
    <div>Организация по оценке</div><div>ОАО "Стройкомплекс"</div>
    <div>Заявитель</div><div>ООО «ЕДАРС»</div>
    <div>УНП заявителя</div><div>791328560</div>
    <div>Адрес</div><div>г. Могилев</div>
    <div>Дата выдачи</div><div>31.10.2025</div>
    <div>Действителен до</div><div>31.10.2030</div>
    <div>Статус</div><div>ДЕЙСТВИТЕЛЕН</div>
    </body></html>'''
    rows = parse_spk(spk_html)
    assert len(rows) == 1 and rows[0]['organization'] == 'ООО «ЕДАРС»' and rows[0]['unp'] == '791328560'

    att_html = '''<table><tr>
    <td>ООО «ВентИнстал»</td><td>г. Минск</td><td>0007056-ГС</td>
    <td>четвертая категория</td><td>22.05.2026</td><td>13.08.2026</td><td>2025: Соответствует</td>
    </tr></table>'''
    rows = parse_att(att_html)
    assert len(rows) == 1 and rows[0]['cert_number'] == '0007056-ГС' and rows[0]['organization'] == 'ООО «ВентИнстал»'

    spk2_html = '''<html><body>
    <div>Регистрационный номер свидетельства</div><div>05890263.2285-2026</div>
    <div>Юридическое лицо</div><div>ОАО «СТРОЙКОМПЛЕКС»</div>
    <div>УНП</div><div>190000000</div>
    <div>Дата регистрации свидетельства</div><div>30.07.2026</div>
    <div>Дата окончания действия свидетельства</div><div>29.07.2031</div>
    <div>Статус действия свидетельства</div><div>ДЕЙСТВИТЕЛЬНО</div>
    </body></html>'''
    rows = parse_spk2(spk2_html)
    assert len(rows) == 1 and rows[0]['cert_number'] == '05890263.2285-2026' and rows[0]['organization'] == 'ОАО «СТРОЙКОМПЛЕКС»'

    print('Parser self-test: OK')


if __name__ == '__main__':
    main()
