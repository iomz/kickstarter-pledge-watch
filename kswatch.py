#!/usr/bin/env python3

# Copyright 2013, Timur Tabi
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#  * Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# This software is provided by the copyright holders and contributors "as is"
# and any express or implied warranties, including, but not limited to, the
# implied warranties of merchantability and fitness for a particular purpose
# are disclaimed. In no event shall the copyright holder or contributors be
# liable for any direct, indirect, incidental, special, exemplary, or
# consequential damages (including, but not limited to, procurement of
# substitute goods or services; loss of use, data, or profits; or business
# interruption) however caused and on any theory of liability, whether in
# contract, strict liability, or tort (including negligence or otherwise)
# arising in any way out of the use of this software, even if advised of
# the possibility of such damage.

import os
import sys
import time
from html import unescape
from html.parser import HTMLParser
from lxml.html import fromstring
from optparse import OptionParser

import configparser
import requests

USER_KEY = "USER_KEY_HERE"
APP_TOKEN = "APP_TOKEN_HERE"
PRIORITY = 1

# Parse the pledge HTML page
#
# It looks like this:
#
# <li class="reward shipping" ...>
# <input alt="$75.00" ... title="$75.00" />
# ...
# </li>
#
# So we need to scan the HTML looking for <li> tags with the proper class,
# (the class is the status of that pledge level), and then remember that
# status as we parse inside the <li> block.  The <input> tag contains a title
# with the pledge amount.  We return a list of tuples that include the pledge
# level, the reward ID, and a description
#
# The 'rewards' dictionary uses the reward value as a key, and
# (status, remaining) as the value.


class KickstarterHTMLParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.in_li_block = False  # True == we're inside an <li class='...'> block
        self.in_desc_block = False  # True == we're inside a <p class="description short"> block
        self.name = ''

    def process(self, url):
        res = requests.get(url)
        self.name = fromstring(res.content).findtext('.//title')
        self.rewards = []
        self.feed(res.text)  # feed() starts the HTMLParser parsing
        return self.rewards

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)

        # It turns out that we only care about tags that have a 'class' attribute
        if not 'class' in attrs:
            return

        # The pledge description is in a 'h3' block that has a 'class'
        # attribute of 'pledge__title'.
        if self.in_li_block and 'pledge__title' in attrs['class']:
            self.in_desc_block = True

        # Extract the pledge amount (the cost)
        if self.in_li_block and tag == 'input' and 'pledge__radio' in attrs['class']:
            # remove everything except the actual number
            self.value = attrs['title'].encode('ascii', 'ignore').decode()
            self.ident = attrs['id']  # Save the reward ID

        # We only care about certain kinds of reward levels -- those that
        # are limited.
        if tag == 'li' and 'pledge--all-gone' in attrs['class']:
            self.in_li_block = True
            self.description = ''

    def handle_endtag(self, tag):
        if tag == 'li':
            if self.in_li_block:
                self.rewards.append((self.value,
                    self.ident,
                    ' '.join(self.description.split())))
                self.in_li_block = False
        if tag == 'h3':
            self.in_desc_block = False

    def handle_data(self, data):
        if self.in_desc_block:
            self.description += unescape(data).encode('ascii', 'ignore').decode()

    def result(self):
        return self.rewards

def push_message(message, url):
    requests.post("https://api.pushover.net/1/messages.json", data={
        "token": APP_TOKEN,
        "user": USER_KEY,
        "priority": PRIORITY,
        "message": message,
        "url": url,
        })

def pledge_menu(rewards):
    import re

    count = len(rewards)

    # If there is only one qualifying pledge level, then just select it
    if count == 1:
        print('Automatically selecting the only limited award available:')
        print('{0} {1}'.format(rewards[0][0], rewards[0][2][:74]))
        return rewards

    for i in xrange(count):
        print('{0}. {1} {2}'.format(i + 1, rewards[i][0], rewards[i][2][:70]))

    while True:
        try:
            ans = raw_input('\nSelect pledge levels: ')
            numbers = map(int, ans.split())
            return [rewards[i - 1] for i in numbers]
        except (IndexError, NameError, SyntaxError):
            continue

parser = OptionParser(usage="usage: %prog [options] project-url [cost-of-pledge ...]\n"
        "project-url is the URL of the Kickstarter project\n"
        "cost-of-pledge is the cost of the target pledge.\n"
        "If cost-of-pledge is not specified, then a menu of pledges is shown.\n"
        "Specify cost-of-pledge only if that amount is unique among pledges.\n"
        "Only restricted pledges are supported.")
parser.add_option("-d", dest="delay",
        help="delay, in minutes, between each check (default is 1)",
        type="int", default=1)
parser.add_option("-v", dest="verbose",
        help="print a message before each delay",
        action="store_true", default=False)
parser.add_option("-c", dest="config_file",
        help="set the config file for credentials",
        type="string", default="kswatch.conf")

(options, args) = parser.parse_args()

if len(args) < 1:
    parser.error('no URL specified')
    sys.exit(0)

# Read the Pushover credentials from the config file
config = configparser.ConfigParser()
config.read(options.config_file)
try:
    USER_KEY = config['pushover']['user_key']
    APP_TOKEN = config['pushover']['app_token']
except:
    pass

# Generate the URL
url = args[0].split('?', 1)[0]  # drop the stuff after the ?
url += '/pledge/new' # we want the pledge-editing page
pledges = None   # The pledge amounts on the command line
ids = None       # A list of IDs of the pledge levels
selected = None  # A list of selected pledge levels
rewards = None  # A list of valid reward levels
if len(sys.argv) > 2:
    pledges = map(float, args[1:])

ks = KickstarterHTMLParser()

rewards = ks.process(url)
if not rewards:
    print('No unavailable limited rewards for this Kickstarter')
    sys.exit(0)

# Select the pledge level(s)
if pledges:
    selected = [r for r in rewards if r[0] in pledges]
else:
    # If a pledge amount was not specified on the command-line, then prompt
    # the user with a menu
    selected = pledge_menu(rewards)

if not selected:
    print('No reward selected.')
    sys.exit(0)

print('\nSelected rewards:')
for s in selected:
    print("{0}".format(s[2]))

print('\nSending test push to make sure everything is OK')
push_message('Start watching: {}'.format(ks.name.strip()), url)

print('\nWatching...')
while True:
    for s in selected:
        if not s[1] in [r[1] for r in rewards]:
            print('{} - Reward available!'.format(time.strftime('%B %d, %Y %I:%M %p')))
            print(string(s[2]))
            push_message('Kickstarter Reward available!', url)
            selected = [x for x in selected if x != s]  # Remove the pledge we just found
            if not selected:  # If there are no more pledges to check, then exit
                time.sleep(10)  # Give the web browser time to open
                sys.exit(0)
            break
    if options.verbose:
        print('Waiting {} minutes ...'.format(options.delay))
    time.sleep(60 * options.delay)

    rewards = ks.process(url)
