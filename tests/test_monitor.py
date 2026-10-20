import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from monitor import filter_slots, parse_datetime, safe_url
CFG={'start_date':'2026-11-04','end_date':'2026-12-15'}
NOW=datetime(2026,10,20,10,tzinfo=ZoneInfo('Australia/Melbourne'))
class Tests(unittest.TestCase):
 def test_date(self):
  self.assertEqual(parse_datetime('2026-11-04T09:35').strftime('%H:%M'),'09:35')
 def test_date_only_rejected(self):
  with self.assertRaises(ValueError):parse_datetime('2026-11-04')
 def test_range(self):
  self.assertEqual(len(filter_slots(['2026-11-03T12:00','2026-11-04T12:00','2026-12-15T13:00','2026-12-16T10:00'],CFG,NOW)),2)
 def test_duplicates(self):
  self.assertEqual(len(filter_slots(['2026-11-04T12:00']*2,CFG,NOW)),1)
 def test_redact(self):
  self.assertEqual(safe_url('https://example.com/calendar?token=secret#foo'),'https://example.com/calendar')
if __name__=='__main__':unittest.main()
