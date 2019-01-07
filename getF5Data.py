import paramiko
import socket
import time
from getpass import getpass
import pandas as pd


# receives SSH connection to individual F5 partitions and populates dictionary with pool members and status
def get_pool_info(remote_conn, pool_dict, partition):
    remote_conn.send("list ltm pool\n")
    # sleep necessary to ensure there's time to receive all output
    time.sleep(3)

    if remote_conn.recv_ready():
        output = remote_conn.recv(65535).decode('utf-8')
        #print(output, file=open('test.txt', 'a'))

    # iterator for SSH output.
    my_iter = iter(output.split('\n'))
    monitor_counter = 0
    current_mode = ' '
    # iterate through each line out SSH output to pull data
    for line in my_iter:
        if 'ltm pool' in line and '{' in line:
            # lines must be split by white space to isolate strings
            pool_line = line.split(' ')
            # set pool name to a variable to later append
            current_pool = pool_line[2]
        if 'load-balancing-mode' in line:
            mode_line = line.split(' ')
            # set balancing mode to variable to later append
            current_mode = mode_line[5]
        if ':' in line and '{' in line:
            node_line = line.split(' ')
            pool_dict['Node'].append(node_line[8])
            # because partition, pool, and mode encapsulate each node, they are appended here
            pool_dict['Pool'].append(current_pool)
            pool_dict['Mode'].append(current_mode)
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
        if 'monitor' in line and 'monitor-enabled' not in line:
            monitor_line = line.split(' ')
            current_monitor = monitor_line[5]
            # for as many nodes in the pool, append monitor type
            for i in range(monitor_counter):
                pool_dict['Monitor'].append(current_monitor)
                # reset to 0 in preparation for next pool
            monitor_counter = 0


def establish_connection():
    # open file of IP's to SSH into
    #with open('loadBalancers.txt') as f:
        #ip_list = [x.strip('\n') for x in f]

    # temporary IP to test with. will later input list of IPs
    ip = '10.58.252.97'
    # need loop for exception handling
    login_invalid = True
    # loops until login is successful
    while login_invalid:
        username = input('Enter username: ')
        # inputs while hiding keystrokes
        password = getpass('Enter password: ')
        try:
            remote_conn_pre = paramiko.SSHClient()
            remote_conn_pre.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            remote_conn_pre.connect(ip, timeout=3, port=22, username=username, password=password,
                                    look_for_keys=False, allow_agent=False)
        # in case of invalid credentials
        except paramiko.AuthenticationException:
            print("Authentication failed. Please verify credentials: ")
            break
        # can't SSH
        except paramiko.SSHException:
            print("Unable to establish SSH connection to:", ip)
            continue
        # exception required for timeout errors
        except socket.error:
            print("Unable to establish SSH connection to:", ip)
            continue

        login_invalid = False
        remote_conn = remote_conn_pre.invoke_shell()
        # commands sent to CLI
        output = remote_conn.recv(65535).decode('utf-8')

        # view available partitions
        remote_conn.send("cd Common/\n")
        # must disable pager to view entire output
        remote_conn.send("modify cli preference pager disabled\n")
        remote_conn.send("cd /\n")
        remote_conn.send("list auth partition\n")
        time.sleep(3)

        if remote_conn.recv_ready():
            output = remote_conn.recv(65535).decode('utf-8')
        time.sleep(.5)

        # list of partitions in each load balancer
        partitions = []

        # dictionary for pool members
        pool_dict = {'Partition': [], 'Pool': [], 'Mode': [], 'Monitor': [], 'State': [], 'Node': [], 'Address': []}
        # create list of partitions that need to be accesses
        for line in output.split('\n'):
            if 'PART' in line:
                line_list = line.split(' ')
                partitions.append(line_list[2])
        # get pool and members info on each partition
        for part in partitions:
            remote_conn.send('cd ' + '/' + part + '/' + '\n')
            # paging prompt must be disabled
            remote_conn.send("modify cli preference pager disabled display-threshold 0\n")
            get_pool_info(remote_conn, pool_dict, part)
            # enable paging after done fetching data
            remote_conn.send("modify cli preference pager enabled\n")

    # create data frame to export dictionary to excel file
    df = pd.DataFrame(data=pool_dict)
    writer = pd.ExcelWriter('Pools.xlsx', engine='xlsxwriter')
    df.to_excel(writer)
    writer.save()


def main():
    establish_connection()


if __name__ == '__main__':
    main()