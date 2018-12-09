import curses
import os
import random
import time
import sys

RESOURCE_DIR = '.'

"""
INSTRUCTIONS FOR USE:
0) curses needed
     builtin if not windows
     for windows:
         http://www.lfd.uci.edu/~gohlke/pythonlibs/#curses
1) input text will be sourced from the resource directory
     which must not be empty
     and is the containing folder by default
2) hit keyboard to exit
"""


class MatrixDisplay(object):
    FPS_MAX = 60
    WORKERS = 45  # number of concurrent strings
    DIRECTION = (0,1)#(1, 0)  # each next character takes a step of size (x, y)
    MIN_CHAR_PER_SECOND = 40
    MAX_CHAR_PER_SECOND = 50
    MAX_LEN = 30
    WARM_UP_DURATION = 2  # strings slowly start appearing on screen

    def __init__(self):
        self.screen = curses.initscr()
        self.lines = []
        self.workers = [MatrixWorker(worker_id, self.DIRECTION) for worker_id in range(self.WORKERS)]
        self.refresh_interval = 1.0 / self.FPS_MAX
        temp = (random.randint(self.MIN_CHAR_PER_SECOND, self.MAX_CHAR_PER_SECOND) for _ in range(self.WORKERS))
        self.worker_intervals = [1.0 / chars_per_second for chars_per_second in temp]

        # bookkeeping
        self.cells = dict()  # {cell: worker-id, ..}
        self.recent_additions = set()  # {cell, ..}
        self.recent_removals = set()  # {cell, ..}

        # simulating threading
        self.next_refresh = time.time() + self.refresh_interval
        temp = (interval + time.time() for interval in self.worker_intervals)
        self.next_worker_wake_time = [wake_time + self.WARM_UP_DURATION * random.random() for wake_time in temp]

        # setup curses
        self.screen.nodelay(1)  # auto refresh on
        curses.curs_set(0)  # typing position cursor not shown
        curses.noecho()  # do not print stuff (not that it does)
        curses.start_color()  # allow color use

        # define colors
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_CYAN)
        curses.init_pair(2, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_BLUE, curses.COLOR_BLACK)
        self.init_color = curses.color_pair(1)  # first appears
        self.norm_color = curses.color_pair(2)  # mid-string
        self.poof_color = curses.color_pair(3)  # just before deletion

    def add_file(self, filename):
        if filename:
            self.lines += [line.strip() for line in open(filename) if len(line.strip())]
        return self

    def write(self, value, cell, worker_id):
        self.cells[cell] = (worker_id, value)
        self.screen.addstr(cell[0], cell[1], value, self.init_color)
        self.recent_additions.add(cell)
        if cell in self.recent_removals:
            self.recent_removals.remove(cell)

    def erase(self, cell, worker_id):
        if cell in self.cells:
            owner_id, value = self.cells[cell]
            if worker_id == owner_id:
                del self.cells[cell]
                self.screen.addstr(cell[0], cell[1], value, self.poof_color)
                self.recent_removals.add(cell)
                if cell in self.recent_additions:
                    self.recent_additions.remove(cell)

    def refresh(self):
        self.screen.refresh()

        for cell in self.recent_removals:
            if cell not in self.cells:
                self.screen.addstr(cell[0], cell[1], ' ')
        self.recent_removals.clear()

        for cell in self.recent_additions:
            _, value = self.cells[cell]
            self.screen.addstr(cell[0], cell[1], value, self.norm_color)
        self.recent_additions.clear()

    def step(self):
        if time.time() > self.next_refresh:
            self.next_refresh += self.refresh_interval
            self.refresh()

        for worker_id in range(self.WORKERS):
            if time.time() > self.next_worker_wake_time[worker_id]:
                self.next_worker_wake_time[worker_id] += self.worker_intervals[worker_id]
                self.workers[worker_id].step(self)

    def run(self, time_seconds=1e16):
        time_limit = time.time() + time_seconds
        while time.time() < time_limit:
            self.step()

            # exit on keyboard input
            if self.screen.getch() != -1:
                for worker in self.workers:  # set workers to quit state
                    worker.state = 'exit'
                while self.cells or self.recent_removals:  # clear screen gracefully
                    self.step()
                self.refresh()  # erase last item
                break


class MatrixWorker(object):
    def __init__(self, worker_id, direction_vector):
        self.id = worker_id
        self.text = None
        self.x = self.y = None
        self.dx, self.dy = direction_vector
        self.cells = []
        self.state = 'init'

    def increment_position(self, window_x_max, window_y_max):
        # increment
        self.x += self.dx
        self.y += self.dy

        # loop axis and randomize to make the loop less visually obvious
        # prefer to appear on the longer horizontal edge of the window
        if not (0 <= self.y <= window_y_max):
            self.y %= window_y_max + 1
            self.x = random.randint(0, window_x_max)
        elif not (0 <= self.x <= window_x_max):
            self.x %= window_x_max + 1
            self.y = random.randint(0, window_y_max)

    def step(self, display):
        """
        :type display: MatrixDisplay
        """
        # reset to random
        if self.state == 'init':
            height, width = display.screen.getmaxyx()
            self.text = [char for char in random.choice(display.lines) if 32 < ord(char) < 127]
            self.y = random.randint(0, height - 2)
            self.x = random.randint(0, width - 1)
            self.cells = []
            self.state = 'write'  # immediately start writing (this step)

        # write to cell
        if self.state == 'write':
            if self.text:
                height, width = display.screen.getmaxyx()

                # write to cell
                display.write(self.text.pop(0), (self.y, self.x), self.id)
                self.cells.append((self.y, self.x))

                # step forward
                self.increment_position(width - 1, height - 2)

                # enforce max string length
                if len(self.cells) > display.MAX_LEN:
                    display.erase(self.cells.pop(0), self.id)
            else:
                self.state = 'erase'  # immediately start erasing (this step)

        # erase tail
        if self.state == 'erase':
            if self.cells:
                display.erase(self.cells.pop(0), self.id)

            # reinitialize once tail is erased
            if not self.cells:
                self.state = 'init'  # init next step

        # fast cleanup before closing screen
        if self.state == 'exit':
            # erase twice as fast from the tail end
            if self.cells:
                display.erase(self.cells.pop(0), self.id)
            if self.cells:
                display.erase(self.cells.pop(0), self.id)

            # also erase from the head end
            if self.cells:
                display.erase(self.cells.pop(), self.id)


if __name__ == '__main__':
    screen = MatrixDisplay()

    for path, dir_list, file_list in os.walk(RESOURCE_DIR):
        for text_file in file_list:
            if '.' in text_file and text_file.rsplit('.', 1)[-1] in ['py', 'txt', 'cmd', 'md']:
                print(text_file)
                screen.add_file(os.path.join(path, text_file))

    screen.run()
