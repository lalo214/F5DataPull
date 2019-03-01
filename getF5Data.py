import paramiko
import socket
import time
import pandas as pd
import threading
from getpass import getpass
from openpyxl import load_workbook


class SSHConnection:
    def __init__(self, ip, username, user_pass):
        self.partitions = []
        try:
            self.remote_conn_pre = paramiko.SSHClient()
            self.remote_conn_pre.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.remote_conn_pre.connect(ip, timeout=3, port=22, username=username, password=user_pass,
                                         look_for_keys=False, allow_agent=False)
            self.remote_conn = self.remote_conn_pre.invoke_shell()
            self.find_partitions()
            # in case of invalid credentials
        except paramiko.AuthenticationException:
            print("Authentication failed. Please verify credentials: ")
            # can't SSH
        except paramiko.SSHException:
            print("Unable to establish SSH connection to:", ip)
            # exception required for timeout errors
        except socket.error:
            print("Unable to establish SSH connection to:", ip)

    def get_pool_info(self, remote_conn, pool_dict, partition):
        remote_conn.send("list ltm pool\n")
        # sleep necessary to ensure there's time to receive all output
        time.sleep(8)

        if remote_conn.recv_ready():
            output = remote_conn.recv(150000).decode('utf-8')
            print(output, file=open('test.txt', 'a'))

            # iterator for SSH output.
        my_iter = iter(output.split('\n'))
        monitor_counter = 0
        current_mode = ' '
        # keeps track if there's a mode available
        has_mode = False
        has_description = False
        # iterate through each line out SSH output to pull data
        for line in my_iter:
            if 'ltm pool' in line and '{' in line:
                # lines must be split by white space to isolate strings
                pool_line = line.split(' ')
                # set pool name to a variable to later append
                current_pool = pool_line[2]
            if 'description' in line:
                has_description = True
                dscr_line = line.split(' ')
                dscr = ''.join(dscr_line[5:])
            if 'load-balancing-mode' in line:
                has_mode = True
                mode_line = line.split(' ')
                # set balancing mode to variable to later append
                current_mode = mode_line[5]
            if ':' in line and '{' in line:
                member_line = line.split(' ')
                pool_dict['Member'].append(member_line[8])
                # because partition, pool, and mode encapsulate each Member, they are appended here
                pool_dict['Pool'].append(current_pool)
                if has_mode:
                    pool_dict['Mode'].append(current_mode)
                else:
                    pool_dict['Mode'].append('N/A')
                if has_description:
                    pool_dict['Description'].append(dscr)
                else:
                    pool_dict['Description'].append('N/A')
                pool_dict['Partition'].append(partition)
                # counter for appending monitor name below
                monitor_counter += 1
            if 'address' in line:
                address_line = line.split(' ')
                pool_dict['Address'].append(address_line[13])
            # if there is no monitor and state available
            if 'address' in line and '}' in next(my_iter):
                pool_dict['State'].append('N/A')
                pool_dict['Monitor'].append('N/A')
                # brings counter back to 0 when there's no monitor
                monitor_counter -= 1
            if 'state' in line:
                state_line = line.split(' ')
                pool_dict['State'].append(state_line[13])
            # in the case that there is more than one monitor
            if 'monitor' in line and 'and' in line:
                monitor_line = line.split(' ')
                monitor_line2 = []
                for i in range(len(monitor_line)):
                    if monitor_line[i] != '' and monitor_line[i] != 'monitor' and monitor_line[i] != 'and' \
                            and monitor_line[i] != '\r':
                        monitor_line2.append(monitor_line[i])
                monitors = ' and '.join(monitor_line2)
                for i in range(monitor_counter):
                    pool_dict['Monitor'].append(monitors)
                monitor_counter = 0
            elif 'monitor min' in line and '{' in line:
                monitor_line = line.split(' ')
                monitor_line2 = []
                for i in range(len(monitor_line)):
                    if monitor_line != '' and monitor_line != '\r':
                        monitor_line2.append(monitor_line[i])
                monitors = ' '.join(monitor_line2)
                for i in range(monitor_counter):
                    pool_dict['Monitor'].append(monitors)
                monitor_counter = 0
            # only one monitor
            elif 'monitor' in line and 'monitor-enabled' not in line:
                monitor_line = line.split(' ')
                current_monitor = monitor_line[5]
                # for as many members in the pool, append monitor type
                for i in range(monitor_counter):
                    pool_dict['Monitor'].append(current_monitor)
                    # reset to 0 in preparation for next pool
                monitor_counter = 0

            if 'min-active-members' in line:
                line2 = next(my_iter)
                if 'monitor' in line2:
                    monitor_line = line2.split(' ')
                    current_monitor = monitor_line[5]
                    for i in range(monitor_counter):
                        pool_dict['Monitor'].append(current_monitor)
                    monitor_counter = 0
                else:
                    for i in range(monitor_counter):
                        if len(pool_dict['State']) < len(pool_dict['Member']):
                            pool_dict['State'].append('N/A')

                        if len(pool_dict['Monitor']) < len(pool_dict['Member']):
                            pool_dict['Monitor'].append('N/A')
                    monitor_counter = 0
            if 'partition' in line:
                has_mode = False
                has_description = False

    def find_partitions(self):
        self.remote_conn.send('cd /Common/\n')
        # remember to enable afterwards
        self.remote_conn.send('modify cli preference pager disabled\n')
        self.remote_conn.send('cd /\n')
        self.remote_conn.send('list auth partition\n')
        time.sleep(2)

        if self.remote_conn.recv_ready():
            output = self.remote_conn.recv(65535).decode('utf-8')

        for line in output.split('\n'):
            if 'PART' in line:
                line_list = line.split(' ')
                self.partitions.append(line_list[2])

    def get_pool_dict(self):
        pool_dict = {'Partition': [], 'Pool': [], 'Mode': [], 'Monitor': [], 'State': [], 'Member': [], 'Address': [],
                     'Description': []}

        for part in self.partitions:
            print(part)
            self.remote_conn.send('cd ' + '/' + part + '/' + '\n')
            # # paging prompt must be disabled
            self.remote_conn.send("modify cli preference pager disabled display-threshold 0\n")
            self.get_pool_info(self.remote_conn, pool_dict, part)
            # enable paging after done fetching data
            self.remote_conn.send("modify cli preference pager enabled\n")

        self.remote_conn.close()
        return pool_dict


def handle_connection(ip, username, password, writer):
    ssh_connection = SSHConnection(ip, username, password)
    # dictionary for pool members
    pool_dict = ssh_connection.get_pool_dict()
    # print(len(pool_dict['Partition']))
    # print(len(pool_dict['Pool']))
    # print(len(pool_dict['Mode']))
    # print(len(pool_dict['Monitor']))
    # print(len(pool_dict['State']))
    # print(len(pool_dict['Member']))
    # print(len(pool_dict['Address']))
    df = pd.DataFrame(data=pool_dict)
    df.to_excel(writer, sheet_name=ip)
    del ssh_connection


def main():
    with open('devices.txt') as f:
        device_list = [x.strip('\n') for x in f]

    username = input('Enter username: ')
    passw = getpass('Enter password: ')
    book = load_workbook('Pools.xlsx')
    writer = pd.ExcelWriter('Pools.xlsx', engine='openpyxl')
    writer.book = book
    for ip in device_list:
        my_thread = threading.Thread(target=handle_connection, args=(ip, username, passw, writer))
        my_thread.start()

    main_thread = threading.currentThread()

    # enumarate() returns list of thread objects currently alive including main thread
    for some_thread in threading.enumerate():
        if some_thread != main_thread:
            print(some_thread)
            some_thread.join()

    writer.save()
    writer.close()


if __name__ == "__main__":
    main()
