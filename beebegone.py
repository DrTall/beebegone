#!/usr/bin/python
"""
Searches your Gmail inbox for emails that look like they're from the
Beeminder Bot and archives them if the goal they're nagging you about has
data newer than the reminder.

This script only checks the datestamp on goal data. You might still be about
to derail the goal, so you might need to be careful if it's an eep day and
you've put in some data but not enough to give a safe day.

Setup:
1. pip install google-api-python-client
2. Follow instructions in secrets.py.
3. Run ./beebegone.py and authorize the app in the web browser. Future runs
won't require human interaction as long as you save your gmail.storage
credentials.

Example Usage:
./beebegone.py
"""

import httplib2
import re
import urllib
import json
import urllib2
import datetime

from apiclient.discovery import build
from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage
from oauth2client.tools import run
from apiclient import errors

import secrets

# Try to retrieve Gmail credentials from storage or generate them
HTTP = httplib2.Http()
STORAGE = Storage('gmail.storage')
credentials = STORAGE.get()
if credentials is None or credentials.invalid:
  credentials = run(flow_from_clientsecrets(
      secrets.CLIENT_SECRET_FILE,
      scope='https://www.googleapis.com/auth/gmail.modify'), STORAGE, http=HTTP)
GMAIL_SERVICE = build('gmail', 'v1', http=credentials.authorize(HTTP))

# Parse the Beeminder nag email subject line.
BEEMINDER_SUBJECT_RE = (
    r'(?P<username>\w+)/(?P<goalname>\w+) on ' +
    r'(?P<month>\d\d)/(?P<day>\d\d) \(.*\).*respond with beeminder data')

thread_ids_to_archive = []
threads = GMAIL_SERVICE.users().threads().list(
    userId='me', labelIds='INBOX').execute() or []
for thread in threads['threads']:
  try:
    message = GMAIL_SERVICE.users().messages().get(
        userId='me', id=thread['id']).execute()
    for header in message['payload']['headers']:
      if header['name'] != 'Subject':
        continue
      matcher = re.match(BEEMINDER_SUBJECT_RE, header['value'])
      if not matcher:
        continue

      print 'Found a beeminder reminder email: %s' % matcher.groupdict()
      beeminder_url = (
          'https://www.beeminder.com/api/v1/users/' +
          '%(username)s/goals/%(goalname)s/datapoints.json' %
          matcher.groupdict())
      beeminder_url += '?' + urllib.urlencode(
          {'auth_token':secrets.BEEMINDER_AUTH_TOKEN})
      try:
        data = json.loads(urllib2.urlopen(beeminder_url).read())
      except (ValueError, urllib2.URLError) as e:
        print "Couldn't parse JSON data from Beeminder: %s" % e
        continue
      if not data:
        continue

      # Assume data is sorted so data[0] is the latest data point.
      date = data[0]['daystamp']
      beeminder_data_date = datetime.datetime.strptime(date, '%Y%m%d')
      gmail_reminder_date = datetime.datetime(
          # This is me punting on all the end of year baloney. Would be more
          # proper to get the date (including year) out of the email itself.
          year=beeminder_data_date.year,
          month=int(matcher.group('month')),
          day=int(matcher.group('day')))
      # Hack around the bogus year data (see above).
      while gmail_reminder_date > datetime.datetime.now():
        gmail_reminder_date -= datetime.timedelta(weeks=52)

      if beeminder_data_date >= gmail_reminder_date:
        print 'Going to archive this email (%s >= %s)' % (
            beeminder_data_date, gmail_reminder_date)
        thread_ids_to_archive.append(thread['id'])
      else:
        print 'Skipping this email (%s < %s)' % (
            beeminder_data_date, gmail_reminder_date)
  except errors.HttpError as e:
    print e

for thread_id in thread_ids_to_archive:
  print 'Archiving thread (id=%s)' % thread_id
  thread = GMAIL_SERVICE.users().threads().modify(
      userId='me', id=thread_id, body={'removeLabelIds': ['INBOX']}).execute()
print 'Done! Archived %s email(s).' % len(thread_ids_to_archive)
