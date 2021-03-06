import os
import pyexcel as pe
from datetime import time, timedelta
from dateutil.parser import parse
from collections import defaultdict, namedtuple
from automated_sla_tool.src.BucketDict import BucketDict
from automated_sla_tool.src.AReport import AReport


class SlaReport(AReport):

    def __init__(self, report_date=None):
        super(SlaReport, self).__init__(report_dates=report_date)
        self.finished = False
        finished, report = self.report_finished(report_date_datetime=report_date)
        if finished:
            self.final_report = pe.get_sheet(file_name=report)
            self.final_report.name = r'{}_Incoming DID Summary'.format(report_date.strftime('%m%d%Y'))
            self.finished = finished
            print('Report Complete.')
        else:
            print('Building a report for {}'.format(self.dates.strftime('%A %m/%d/%Y')))
            self.clients = self.get_client_settings()
            self.clients_verbose = self.make_verbose_dict()
            self.src_doc_path = None
            self.login_type = r'imap.gmail.com'
            self.user_name = r'mindwirelessreporting@gmail.com'
            self.password = r'7b!2gX4bD3'
            self.converter_arg = r'{0}\{1}'.format(self.path, r'converter\ofc.ini')
            self.converter_exc = r'{0}\{1}'.format(self.path, r'converter\ofc.exe')
            self.active_directory = r'{0}\{1}'.format(self.path, r'active_files')
            self.voicemail = defaultdict(list)
            self.orphaned_voicemails = None
            self.sla_report = {}

    '''
    UI Section
    '''
    # def __decorator(self, func):
    #     if self.finished:
    #         print('finished. returning')
    #         return
    #     else:
    #         print('returning process')
    #         return func
    #
    # @__decorator
    def download_documents(self):
        '''

        :return:
        '''
        if self.finished:
            return
        else:
            self.download_src_files()
            src_file_directory = os.listdir(self.src_doc_path)
            for file in src_file_directory:
                if file.endswith(".xls"):
                    self.copy_and_convert(self.src_doc_path, src_file_directory)
                    break

    def load_documents(self):
        '''

        :return:
        '''
        if self.finished:
            return
        else:
            call_details_file = r'{0}\{1}'.format(self.src_doc_path, r'Call Details (Basic).xlsx')
            abandon_group_file = r'{0}\{1}'.format(self.src_doc_path, r'Group Abandoned Calls.xlsx')
            cradle_to_grave_file = r'{0}\{1}'.format(self.src_doc_path, r'Cradle to Grave.xlsx')

            call_details = pe.get_sheet(file_name=call_details_file)
            if self.check_valid_date(call_details['A2']) is not True:
                raise ValueError('Invalid date for file {}'.format(call_details_file))
            self.call_details = self.filter_call_details(call_details)
            self.call_details.name_columns_by_row(0)
            self.call_details.name = 'call_details'

            abandon_group = pe.get_book(file_name=abandon_group_file)
            del abandon_group['Summary']
            if self.check_valid_date(abandon_group[0]['A3']) is not True:
                raise ValueError('Invalid date for file {}'.format(abandon_group_file))
            abandon_group = self.merge_sheets(abandon_group)
            self.abandon_group = self.make_distinct_and_sort(abandon_group)
            self.abandon_group.name_columns_by_row(0)
            self.abandon_group.name = 'abandon_group'

            cradle_to_grave = pe.get_book(file_name=cradle_to_grave_file)
            del cradle_to_grave['Summary']
            if self.check_valid_date(cradle_to_grave[0]['A3']) is not True:
                raise ValueError('Invalid date for file {}'.format(cradle_to_grave_file))
            cradle_filter = pe.RowValueFilter(self.cradle_report_row_filter)
            for sheet in cradle_to_grave:
                sheet.filter(cradle_filter)
                sheet.name_columns_by_row(0)
            self.cradle_to_grave = cradle_to_grave

            self.get_voicemails()

    def compile_call_details(self):
        '''

                :return:
                '''
        if self.finished:
            return
        else:
            client = namedtuple('this_client',
                                'hold_amount park_amount conference_amount transfer_amount additional_time')
            client.__new__.__defaults__ = (0,) * len(client._fields)
            additional_times = [['Wait Time', 'Hold Time']]

            col_index = self.call_details.colnames

            for row in self.call_details.rows():
                call_id = row[col_index.index('Call')].replace(':', ' ')
                sheet = self.cradle_to_grave[call_id]
                sheet_events = sheet.column['Event Type']
                transfer_hold = 'Transfer Hold' in sheet_events
                had_hold = 'Hold' in sheet_events
                had_park = 'Park' in sheet_events
                had_conference = 'Conference' in sheet_events
                call_duration = self.get_sec(row[col_index.index('Call Duration')])
                talk_duration = self.get_sec(row[col_index.index('Talking Duration')])
                if (transfer_hold or had_hold or had_park or had_conference) is True:
                    event_durations = sheet.column['Event Duration']
                    this_client = client(hold_amount=self.correlate_list_data(sheet_events,
                                                                              event_durations,
                                                                              'Hold'),
                                         park_amount=self.correlate_list_data(sheet_events,
                                                                              event_durations,
                                                                              'Park'),
                                         conference_amount=self.correlate_list_data(sheet_events,
                                                                                    event_durations,
                                                                                    'Conference'),
                                         transfer_amount=self.correlate_list_data(sheet_events,
                                                                                  event_durations,
                                                                                  'Transfer Hold'))
                    if transfer_hold is True and had_conference is False:
                        transfer_hold_index = sheet_events.index('Transfer Hold')
                        this_client = this_client._replace(
                            additional_time=self.correlate_list_data(sheet_events[transfer_hold_index:],
                                                                     event_durations[transfer_hold_index:],
                                                                     'Talking')
                        )
                    client_sum = sum(int(i) for i in this_client)
                    wait_time = self.convert_time_stamp((call_duration - talk_duration) - client_sum)
                    additional_times.append([wait_time, self.convert_time_stamp(client_sum)])
                else:
                    wait_time = self.convert_time_stamp((call_duration - talk_duration))
                    additional_times.append([wait_time, self.convert_time_stamp(0)])
            additional_time_column = pe.Sheet(additional_times)
            self.call_details.column += additional_time_column

    def scrutinize_abandon_group(self):
        '''

                :return:
                '''
        if self.finished:
            return
        else:
            self.remove_calls_less_than_twenty_seconds()
            self.remove_duplicate_calls()

    def extract_report_information(self):
        # TODO: might be nice to thread reading the reports
        '''

                :return:
                '''
        if self.finished:
            return
        else:
            client_ans = self.read_report(self.call_details)
            client_lost = self.read_report(self.abandon_group)
            for client in self.clients.keys():
                calls_answered = self.get_client_info(client_ans, client)
                calls_lost = self.get_client_info(client_lost, client)
                voicemails = self.get_client_info(self.voicemail, self.clients[client].name)
                self.sla_report[client] = Client(name=client,
                                                 answered_calls=calls_answered,
                                                 lost_calls=calls_lost,
                                                 voicemail=voicemails,
                                                 full_service=self.clients[client].full_service)
                if self.sla_report[client].is_empty():
                    pass
                else:
                    if self.sla_report[client].no_answered() is False:
                        self.sla_report[client].extract_call_details(self.call_details)
                    if self.sla_report[client].no_lost() is False:
                        self.sla_report[client].extract_abandon_group_details(self.abandon_group)

    def process_report(self):
        '''

                :return:
                '''
        if self.finished:
            return
        else:
            headers = [self.dates.strftime('%A %m/%d/%Y'), 'I/C Presented', 'I/C Answered', 'I/C Lost', 'Voice Mails',
                       'Incoming Answered (%)', 'Incoming Lost (%)', 'Average Incoming Duration', 'Average Wait Answered',
                       'Average Wait Lost', 'Calls Ans Within 15', 'Calls Ans Within 30', 'Calls Ans Within 45',
                       'Calls Ans Within 60', 'Calls Ans Within 999', 'Call Ans + 999', 'Longest Waiting Answered', 'PCA']
            self.final_report.row += headers
            total_row = dict((value, 0) for value in headers[1:])
            total_row['Label'] = 'Summary'
            for client in sorted(self.clients.keys()):
                answered, lost, voicemails = self.sla_report[client].get_number_of_calls()
                this_row = dict((value, 0) for value in headers[1:])
                this_row['I/C Presented'] = answered + lost + voicemails
                this_row['Label'] = '{0} {1}'.format(client, self.clients[client].name)
                if this_row['I/C Presented'] > 0:
                    ticker_stats = self.sla_report[client].get_call_ticker()
                    this_row['I/C Answered'] = answered
                    this_row['I/C Lost'] = lost
                    this_row['Voice Mails'] = voicemails
                    this_row['Incoming Answered (%)'] = (answered / this_row['I/C Presented'])
                    this_row['Incoming Lost (%)'] = ((lost + voicemails) / this_row['I/C Presented'])
                    this_row['Average Incoming Duration'] = self.sla_report[client].get_avg_call_duration()
                    this_row['Average Wait Answered'] = self.sla_report[client].get_avg_wait_answered()
                    this_row['Average Wait Lost'] = self.sla_report[client].get_avg_lost_duration()
                    this_row['Calls Ans Within 15'] = ticker_stats[15]
                    this_row['Calls Ans Within 30'] = ticker_stats[30]
                    this_row['Calls Ans Within 45'] = ticker_stats[45]
                    this_row['Calls Ans Within 60'] = ticker_stats[60]
                    this_row['Calls Ans Within 999'] = ticker_stats[999]
                    this_row['Call Ans + 999'] = ticker_stats[999999]
                    this_row['Longest Waiting Answered'] = self.sla_report[client].get_longest_answered()
                    try:
                        this_row['PCA'] = ((ticker_stats[15] + ticker_stats[30]) / answered)
                    except ZeroDivisionError:
                        this_row['PCA'] = 0

                    self.accumulate_total_row(this_row, total_row)
                    self.format_row(this_row)
                    self.final_report.row += self.return_row_as_list(this_row)
                else:
                    self.format_row(this_row)
                    self.final_report.row += self.return_row_as_list(this_row)
            self.finalize_total_row(total_row)
            self.format_row(total_row)
            self.final_report.row += self.return_row_as_list(total_row)

    def save_report(self):
        the_directory = os.path.dirname(self.path)
        the_file = r'{0}_Incoming DID Summary.xlsx'.format(self.dates.strftime("%m%d%Y"))
        self.final_report.save_as(r'{0}\Output\{1}'.format(the_directory, the_file))

    '''
    Utilities Section
    '''
    def format_row(self, row):
        row['Average Incoming Duration'] = self.convert_time_stamp(row['Average Incoming Duration'])
        row['Average Wait Answered'] = self.convert_time_stamp(row['Average Wait Answered'])
        row['Average Wait Lost'] = self.convert_time_stamp(row['Average Wait Lost'])
        row['Longest Waiting Answered'] = self.convert_time_stamp(row['Longest Waiting Answered'])
        row['Incoming Answered (%)'] = '{0:.1%}'.format(row['Incoming Answered (%)'])
        row['Incoming Lost (%)'] = '{0:.1%}'.format(row['Incoming Lost (%)'])
        row['PCA'] = '{0:.1%}'.format(row['PCA'])

    def return_row_as_list(self, row):
        return [row['Label'],
                row['I/C Presented'],
                row['I/C Answered'],
                row['I/C Lost'],
                row['Voice Mails'],
                row['Incoming Answered (%)'],
                row['Incoming Lost (%)'],
                row['Average Incoming Duration'],
                row['Average Wait Answered'],
                row['Average Wait Lost'],
                row['Calls Ans Within 15'],
                row['Calls Ans Within 30'],
                row['Calls Ans Within 45'],
                row['Calls Ans Within 60'],
                row['Calls Ans Within 999'],
                row['Call Ans + 999'],
                row['Longest Waiting Answered'],
                row['PCA']]

    def accumulate_total_row(self, row, tr):
        tr['I/C Presented'] += row['I/C Presented']
        tr['I/C Answered'] += row['I/C Answered']
        tr['I/C Lost'] += row['I/C Lost']
        tr['Voice Mails'] += row['Voice Mails']
        tr['Average Incoming Duration'] += row['Average Incoming Duration'] * row['I/C Answered']
        tr['Average Wait Answered'] += row['Average Wait Answered'] * row['I/C Answered']
        tr['Average Wait Lost'] += row['Average Wait Lost'] * row['I/C Lost']
        tr['Calls Ans Within 15'] += row['Calls Ans Within 15']
        tr['Calls Ans Within 30'] += row['Calls Ans Within 30']
        tr['Calls Ans Within 45'] += row['Calls Ans Within 45']
        tr['Calls Ans Within 60'] += row['Calls Ans Within 60']
        tr['Calls Ans Within 999'] += row['Calls Ans Within 999']
        tr['Call Ans + 999'] += row['Call Ans + 999']
        if tr['Longest Waiting Answered'] < row['Longest Waiting Answered']:
            tr['Longest Waiting Answered'] = row['Longest Waiting Answered']

    def finalize_total_row(self, tr):
        tr['Incoming Answered (%)'] = tr['I/C Answered'] / tr['I/C Presented']
        tr['Incoming Lost (%)'] = (tr['I/C Lost'] + tr['Voice Mails']) / tr['I/C Presented']
        tr['Average Incoming Duration'] //= tr['I/C Answered']
        tr['Average Wait Answered'] //= tr['I/C Answered']
        tr['Average Wait Lost'] //= tr['I/C Lost']
        tr['PCA'] = (tr['Calls Ans Within 15'] + tr['Calls Ans Within 30']) / tr['I/C Presented']

    def check_valid_date(self, doc_date):
        try:
            date_time = parse(doc_date.split(' - ')[0]).date()
        except ValueError:
            return False
        else:
            if (date_time - self.dates) <= timedelta(days=1):
                return True
            else:
                return False

    def make_verbose_dict(self):
        return dict((value.name, key) for key, value in self.clients.items())

    def download_src_files(self):
        # TODO: remove my email from this once live
        '''
        Temporary
        self.login_type = r'imap.gmail.com'
        self.user_name = r'mindwirelessreporting@gmail.com'
        self.password = r'7b!2gX4bD3'
        '''
        import email
        import imaplib
        file_dir = r'{0}\{1}\{2}'.format(os.path.dirname(self.path), 'Attachment Archive', self.dates.strftime('%m%d'))
        try:
            os.chdir(file_dir)
        except FileNotFoundError:
            try:
                os.makedirs(file_dir, exist_ok=True)
                os.chdir(file_dir)
            except OSError:
                pass

        self.src_doc_path = os.getcwd()
        if not os.listdir(self.src_doc_path):
            try:
                imap_session = imaplib.IMAP4_SSL(r'secure.emailsrvr.com')
                status, account_details = imap_session.login(r'mscales@mindwireless.com', r'wireless1!')
                if status != 'OK':
                    raise ValueError('Not able to sign in!')

                imap_session.select("Inbox")
                on = "ON " + (self.dates + timedelta(days=1)).strftime("%d-%b-%Y")
                status, data = imap_session.uid('search', on, 'FROM "Chronicall Reports"')
                if status != 'OK':
                    raise ValueError('Error searching Inbox.')

                # Iterating over all emails
                for msg_id in data[0].split():
                    status, message_parts = imap_session.uid('fetch', msg_id, '(RFC822)')
                    if status != 'OK':
                        raise ValueError('Error fetching mail.')

                    mail = email.message_from_bytes(message_parts[0][1])
                    for part in mail.walk():
                        if part.get_content_maintype() == 'multipart':
                            continue
                        if part.get('Content-Disposition') is None:
                            continue
                        file_name = part.get_filename()

                        if bool(file_name):
                            file_path = os.path.join(file_name)
                            if not os.path.isfile(file_path):
                                fp = open(file_path, 'wb')
                                fp.write(part.get_payload(decode=True))
                                fp.close()

                imap_session.close()
                imap_session.logout()

            except Exception as err:
                raise ValueError('Not able to download all attachments. Error: {}'.format(err))
        else:
            print("Files already downloaded.")

    def copy_and_convert(self, file_location, directory):
        from shutil import move
        for src_file in directory:
            if src_file.endswith(".xls"):
                src = os.path.join(file_location, src_file)
                des = os.path.join(self.active_directory, src_file)
                move(src, des)

        import subprocess as proc
        proc.run([self.converter_exc, self.converter_arg])
        filelist = [f for f in os.listdir(self.active_directory) if f.endswith(".xls")]
        for f in filelist:
            f = os.path.join(self.active_directory, f)
            os.remove(f)

        for src_file in os.listdir(self.active_directory):
            src = os.path.join(self.active_directory, src_file)
            des = os.path.join(file_location, src_file)
            move(src, des)

    def merge_sheets(self, workbook):
        merged_sheet = pe.Sheet()
        abandon_filter = pe.RowValueFilter(self.abandon_group_row_filter)
        first_sheet = True
        for sheet in workbook:
            sheet.filter(abandon_filter)
            if first_sheet:
                merged_sheet.row += sheet
                first_sheet = False
            else:
                sheet.name_columns_by_row(0)
                merged_sheet.row += sheet
        return merged_sheet

    def abandon_group_row_filter(self, row):
        unique_cell = row[0].split(' ')
        return unique_cell[0] != 'Call'

    def blank_row_filter(self, row):
        result = [element for element in row[3] if element != '']
        return len(result) == 0

    def inbound_call_filter(self, row):
        return row[1] not in "Inbound 'Call Direction'"

    def zero_duration_filter(self, row):
        result = [element for element in row[-1] if element != '']
        return len(result) == 0

    def remove_internal_inbound_filter(self, row):
        return row[-2] == row[-3] == row[-4]

    def cradle_report_row_filter(self, row):
        result = row[0].split(' ')
        return result[0] != 'Event'

    def make_distinct_and_sort(self, worksheet):
        worksheet.name_rows_by_column(0)
        sorted_list = [item for item in sorted(worksheet.rownames, reverse=False) if '-' not in item]
        new_sheet = pe.Sheet()
        for item in sorted_list:
            temp_list = worksheet.row[item]
            temp_list.insert(0, item)
            new_sheet.row += temp_list
        return new_sheet

    def find(self, lst, a):
        return [i for i, x in enumerate(lst) if x == a]

    def find_non_distinct(self, lst):
        icount = {}
        for i in lst:
            icount[i] = icount.get(i, 0) + 1
        return {k: v for k, v in icount.items() if v > 1}

    def correlate_list_data(self, src_list, list_to_correlate, key):
        return_value = 0
        for event in self.find(src_list, key):
            return_value += self.get_sec(list_to_correlate[event])
        return return_value

    def read_report(self, report):
        report_details = defaultdict(list)
        col_index = report.colnames
        for row in report.rows():
            call_id = row[col_index.index('Call')]
            try:
                client = int(row[col_index.index('Internal Party')])
            except ValueError:
                client = self.handle_read_value_error(call_id)
            finally:
                report_details[client].append(call_id)
        return report_details

    def handle_read_value_error(self, call_id):
        sheet = self.cradle_to_grave[call_id.replace(':', ' ')]
        hunt_index = sheet.column['Event Type'].index('Ringing')
        return sheet.column['Receiving Party'][hunt_index]

    def get_client_info(self, dict, key):
        return_value = None
        try:
            return_value = dict[key]
        except KeyError:
            pass
        finally:
            return return_value

    def filter_call_details(self, call_details):
        call_filter = pe.RowValueFilter(self.blank_row_filter)
        call_details.filter(call_filter)
        inbound_call_filter = pe.RowValueFilter(self.inbound_call_filter)
        call_details.filter(inbound_call_filter)
        zero_duration = pe.RowValueFilter(self.zero_duration_filter)
        call_details.filter(zero_duration)
        internal_inbound = pe.RowValueFilter(self.remove_internal_inbound_filter)
        call_details.filter(internal_inbound)
        return call_details

    def remove_duplicate_calls(self):
        internal_parties = self.abandon_group.column['Internal Party']
        external_parties = self.abandon_group.column['External Party']
        start_times = self.abandon_group.column['Start Time']
        end_times = self.abandon_group.column['End Time']
        potential_duplicates = self.find_non_distinct(external_parties)
        for duplicate in potential_duplicates:
            call_index = self.find(external_parties, duplicate)
            first_call = call_index[0]
            first_call_client = internal_parties[first_call]
            first_call_end_time = parse(end_times[first_call])
            for call in range(1, len(call_index)):
                next_call = call_index[call]
                next_call_client = internal_parties[next_call]
                next_call_start_time = parse(start_times[next_call])
                time_delta = next_call_start_time - first_call_end_time
                if time_delta < timedelta(minutes=1) and first_call_client == next_call_client:
                    del self.abandon_group.row[next_call]

    def remove_calls_less_than_twenty_seconds(self):
        call_durations = self.abandon_group.column['Call Duration']
        for call in call_durations:
            if self.get_sec(call) < 20:
                row_index = call_durations.index(call)
                del self.abandon_group.row[row_index]

    def get_voicemails(self):
        voicemail_file_path = r'{0}\{1}'.format(self.src_doc_path,
                                                r'{}voicemail.txt'.format(self.dates.strftime('%m_%d_%Y')))
        try:
            self.read_voicemail_data(voicemail_file_path)
        except FileNotFoundError:
            self.make_voicemail_data()
            self.write_voicemail_data(voicemail_file_path)

    def read_voicemail_data(self, voicemail_file_path):
        with open(voicemail_file_path) as f:
            content = f.readlines()
            for item in content:
                client_info = item.replace('\n', '').split(',')
                self.voicemail[client_info[0]] = client_info[1:]

    def retrieve_voicemail_emails(self):
        from automated_sla_tool.src.Outlook import Outlook
        mail = Outlook(self.dates, self.login_type)
        mail.login(self.user_name, self.password)
        mail.inbox()
        read_ids = mail.read_ids()
        return mail.get_voice_mail_info(read_ids)

    def retrieve_voicemail_cradle(self):
        voice_mail_dict = defaultdict(list)
        for call_id_page in self.cradle_to_grave:
            col_index = call_id_page.colnames
            sheet_events = call_id_page.column['Event Type']
            if 'Voicemail' in sheet_events:
                voicemail_index = sheet_events.index('Voicemail')
                real_voicemail = call_id_page[
                                     voicemail_index, col_index.index('Receiving Party')] in self.clients_verbose
                if real_voicemail:
                    voicemail = {}
                    receiving_party = call_id_page[voicemail_index, col_index.index('Receiving Party')]
                    telephone_number = str(call_id_page[voicemail_index, col_index.index('Calling Party')])[-4:]
                    if telephone_number.isalpha():
                        telephone_number = str(call_id_page[0, col_index.index('Calling Party')])[-4:]
                    call_time = call_id_page[voicemail_index, col_index.index('End Time')]
                    voicemail['call_id'] = call_id_page.name
                    voicemail['number'] = telephone_number
                    voicemail['call_time'] = call_time
                    voice_mail_dict[receiving_party].append(voicemail)
        return voice_mail_dict

    def make_voicemail_data(self):
        e_vm = self.retrieve_voicemail_emails()
        c_vm = self.retrieve_voicemail_cradle()
        for client, e_list in e_vm.items():
            c_list = c_vm.get(client, None)
            if c_list is None:
                self.voicemail[client] = ['orphan-{}'.format(i.split(' + ')[0]) for i in e_list]
            else:
                for evoicemail in e_list:
                    email_number, email_time = evoicemail.split(' + ')
                    matched_call = next((l for l in c_list if l['number'] == email_number), None)
                    if matched_call is None:
                        self.voicemail[client].append('orphan-{}'.format(email_number))
                    else:
                        email_datetime = parse(email_time)
                        cradle_datetime = parse(matched_call['call_time'])
                        difference = cradle_datetime - email_datetime
                        if difference < timedelta(seconds=31):
                            self.voicemail[client].append(matched_call['call_id'])

    def write_voicemail_data(self, voicemail_file_path):
        text_file = open(voicemail_file_path, 'w')
        for voicemail_group in self.voicemail.items():
            text_string = '{0},{1}\n'.format(voicemail_group[0], ",".join(voicemail_group[1]))
            text_file.write(text_string)
        text_file.close()

    def get_client_settings(self):
        client = namedtuple('client_settings', 'name full_service')
        settings_file = r'{0}\{1}'.format(self.path, r'settings\report_settings.xlsx')
        settings = pe.get_sheet(file_name=settings_file, name_columns_by_row=0)
        return_dict = {}
        for row in range(settings.number_of_rows()):
            this_client = client(name=settings[row, 'Client Name'],
                                 full_service=settings[row, 'Full Service'])
            return_dict[settings[row, 'Client Number']] = this_client
        return return_dict

    def __str__(self):
        for arg in vars(self):
            print(arg)

    def report_finished(self, report_date_datetime=None, return_file=None):
        date_string = report_date_datetime.strftime("%m%d%Y")
        the_directory = r'{0}\Output'.format(os.path.dirname(self.path))
        the_file = r'\{0}_Incoming DID Summary.xlsx'.format(date_string)
        if the_file in os.listdir(the_directory):
            file_exists = True
            return_file = r'{0}{1}'.format(the_directory, the_file)
        else:
            file_exists = False
        return file_exists, return_file


class Client:
    earliest_call = time(hour=7)
    latest_call = time(hour=20)

    def __init__(self, name=None,
                 answered_calls=None,
                 lost_calls=None,
                 voicemail=None,
                 full_service=False):
        self.name = name
        self.full_service = full_service
        self.answered_calls = answered_calls
        self.lost_calls = lost_calls
        self.voicemails = voicemail
        self.remove_voicemails()
        self.longest_answered = 0
        self.call_details_duration = timedelta(seconds=0)
        self.abandon_group_duration = timedelta(seconds=0)
        self.wait_answered = []
        self.call_details_ticker = BucketDict(
            {(-1, 15): 0, (15, 30): 0, (30, 45): 0, (45, 60): 0, (60, 999): 0, (999, 999999): 0}
        )

    def __str__(self):
        print('name: {}'.format(self.name))
        print('ans: {}'.format(self.answered_calls))
        print('lost: {}'.format(self.lost_calls))
        print('vm: {}'.format(self.voicemails))

    def remove_voicemails(self):
        '''
        Should never find a voicemail call since they're excluded when Call Details loads
        :return:
        '''
        for voicemail in self.voicemails:
            if voicemail in self.lost_calls:
                self.lost_calls.remove(voicemail)
            if voicemail in self.answered_calls:
                self.answered_calls.remove(voicemail)

    def is_empty(self):
        return len(self.answered_calls) == 0 and len(self.lost_calls) == 0 and len(self.voicemails) == 0

    def no_answered(self):
        return len(self.answered_calls) == 0

    def no_lost(self):
        return len(self.lost_calls) == 0

    def convert_datetime_seconds(self, datetime_obj):
        return 60 * (datetime_obj.hour * 60) + datetime_obj.minute * 60 + datetime_obj.second

    def extract_call_details(self, call_details):
        self.call_details_duration = self.read_report(report=call_details,
                                                      call_group=self.answered_calls,
                                                      call_ticker=self.call_details_ticker,
                                                      wait_answered=self.wait_answered)

    def extract_abandon_group_details(self, abandon_group):
        self.abandon_group_duration = self.read_report(report=abandon_group,
                                                       call_group=self.lost_calls)

    def read_report(self, report=None, call_group=None, call_ticker=None, wait_answered=None):
        col_index = report.colnames
        call_ids = report.column['Call']
        start_time_index = col_index.index('Start Time')
        call_duration_index = col_index.index('Call Duration')
        duration_counter = timedelta(seconds=0)
        for call in call_group:
            row_index = call_ids.index(call)
            start_time = report[row_index, start_time_index]
            if self.valid_time(parse(start_time)) or self.full_service:
                duration_datetime = parse(report[row_index, call_duration_index])
                converted_seconds = self.convert_datetime_seconds(duration_datetime)
                if report.name == 'call_details' or converted_seconds >= 20:
                    duration_counter += timedelta(seconds=converted_seconds)
                    if call_ticker is not None:
                        wait_duration_index = col_index.index('Wait Time')
                        hold_duration = parse(report[row_index, wait_duration_index])
                        hold_duration_seconds = self.convert_datetime_seconds(hold_duration)
                        wait_answered.append(hold_duration_seconds)
                        call_ticker.add_range_item(hold_duration_seconds)
                        if hold_duration_seconds > self.longest_answered:
                            self.longest_answered = hold_duration_seconds
                else:
                    call_group.remove(call)
            else:
                call_group.remove(call)
        return duration_counter

    def valid_time(self, call_datetime):
        # TODO: call ID are ordered -> check first and last instead of whole call_ID list
        call_time = call_datetime.time()
        return self.earliest_call <= call_time <= self.latest_call

    def get_longest_answered(self):
        return self.longest_answered

    def get_avg_call_duration(self):
        return self.get_avg_duration(current_duration=self.call_details_duration.total_seconds(),
                                     call_group=self.answered_calls)

    def get_avg_lost_duration(self):
        return self.get_avg_duration(current_duration=self.abandon_group_duration.total_seconds(),
                                     call_group=self.lost_calls)

    def get_avg_wait_answered(self):
        return self.get_avg_duration(current_duration=sum(self.wait_answered),
                                     call_group=self.wait_answered)

    def get_avg_duration(self, current_duration=None, call_group=None):
        return_value = current_duration
        try:
            return_value //= len(call_group)
        except ZeroDivisionError:
            pass
        return int(return_value)

    def get_number_of_calls(self):
        return len(self.answered_calls), len(self.lost_calls), len(self.voicemails)

    def chop_microseconds(self, delta):
        return delta - timedelta(microseconds=delta.microseconds)

    def get_call_ticker(self):
        return self.call_details_ticker
