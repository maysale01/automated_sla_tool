import email
import email.mime.multipart
import imaplib
import re
from collections import defaultdict


class Outlook:
    def __init__(self, use_date, login_type):
        self.my_date = use_date
        self.today = self.my_date.strftime("%d-%b-%Y")
        self.IMAP = imaplib.IMAP4_SSL(login_type)

    def login(self, username, password):
        while True:
            try:
                r, d = self.IMAP.login(username, password)
                assert r == 'OK', 'login failed'
                print("Signing in as %s" % username)
                print(d)
            except:
                print(" > Sign In ...")
                continue
            break

    def get_voice_mail_info(self, all_emails):
        voice_mails = defaultdict(list)
        for subject_line in all_emails:
            client_number, phone_number, time_of_call = self.get_tokens(subject_line)
            self.get_tokens(subject_line)
            if client_number != 0:
                voice_mails[client_number].append('{0} + {1} {2}'.format(phone_number, self.today, time_of_call))
        return voice_mails

    def all_ids(self):
        result, data = self.IMAP.uid('search', None, "ALL")
        all_list = []
        if result == 'OK':
            for num in data[0].split():
                result, data = self.IMAP.uid('fetch', num, '(RFC822)')
                if result == 'OK':
                    email_message = email.message_from_bytes(data[0][1])
                    all_list.append(email_message['Subject'])
        return all_list

    def read_ids(self):
        date_sent_on = "ON " + self.today
        result, data = self.IMAP.uid('search', date_sent_on, "ALL")
        read_list = []
        if result == 'OK':
            for num in data[0].split():
                result, data = self.IMAP.uid('fetch', num, '(RFC822)')
                if result == 'OK':
                    email_message = email.message_from_bytes(data[0][1])
                    read_list.append(email_message['Subject'] + email_message['Date'])
        return read_list

    def get_tokens(self, search_string):
        search_object = re.search(r'(.*) > (.*?) .*', search_string, re.M | re.I)
        search_object2 = re.search(r'(.*)' + self.my_date.strftime("%Y") + ' (.*?) .*', search_string, re.M | re.I)
        if search_object:
            phone_number = search_object.group(1).replace('Voicemail', "")
            phone_number = phone_number.replace('Message', "")
            phone_number = phone_number.replace(' ', "")
            phone_number = phone_number.replace('(', "")
            client_number = search_object.group(2).replace(')', "")
            return client_number, phone_number[-4:], search_object2.group(2)
        else:
            return 0, 0, 0

    def inbox(self):
        return self.IMAP.select("Inbox")
