from argparse import ArgumentParser
from pbrt_scheduler.core import SchedulerSlave

def main():
    parser = ArgumentParser()
    parser.add_argument('name', type=str,
                        help='name for communication with master')
    parser.add_argument('--system-host', default='127.0.0.1', type=str,
                        help='host for communication with master')
    parser.add_argument('--system-port', default=13481, type=int,
                        help='port for communication with master')
    parser.add_argument('--heartbeat-interval', default=5, type=int,
                        help='Interval for heartbeat')
    args = parser.parse_args()

    slave = SchedulerSlave(name=args.name, master_host=args.system_host,
                           master_port=args.system_port,
                           heartbeat_interval=args.heartbeat_interval)
    slave.run()

if __name__ == "__main__":
    main()
