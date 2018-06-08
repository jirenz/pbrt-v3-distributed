import time
import sys


def countdown(seconds, prompt='Countdown : {}s'):
    seconds = int(seconds)
    while seconds > 0:
        sys.stdout.write(prompt.format(seconds) + '\r')
        sys.stdout.flush()
        time.sleep(1)
        seconds -= 1