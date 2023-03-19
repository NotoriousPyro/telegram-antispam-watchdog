# Telegram AntiSpam Watchdog

Automatically block telegram private message spammers/scammers.

## What does it do?

This is a python script which runs on Google Compute Engine.

It logs into your Telegram account just like a normal telegram client. Once receiving a private message, it will block the notification and delete it, and then send a verification question as reply.

All private messages from the peer will be marked as read and deleted until the question is answered correctly.

Note that this program will whitelist all messages from Group/Channel (with negative chat id) and Telegram official notification (777000). The current chat will be whitelisted if you send any outgoing messages. The current open chats will also be whitelisted.

These will be saved in Google Datastore.

## How to install and run

1. Sign up to Google Cloud
2. Enable the following APIs:
    * Cloud Datastore API
    * Cloud Logging API
    * Compute Engine API
3. Go to Compute Engine and set up a VM, ec2-micro should suffice and is within the free tier. Make sure to give scope access for:
    * Datastore read/write
    * Logging write
4. SSH to the VM and install `git`, `python3-pip`:
    ```bash
    sudo apt install git python3-pip
    ```
5. Clone:
    ```bash
    git clone https://github.com/NotoriousPyro/telegram-antispam-watchdog.git
    ```
6. Install prereqs:
    ```bash
    python3 -m pip install -r requirements.txt
    ```
7. Copy `config.env.example` to `config.env` and edit the parameters:
    * `GCP_PROJECT_ID` - this is visible in the URL of your gcloud project.
    * `TELEGRAM_API_HASH` and `TELEGRAM_API_ID` are obtainable from [obtaining-api-id](https://core.telegram.org/api/obtaining_api_id#obtaining-api-id).
    * `TELEGRAM_DB_PASSWORD` should be a password, preferably using a password generator.
    * `TELEGRAM_PHONE` should be the phone number associated to your Telegram account.
    (optional) Specify your own question/answer:
    * `YOUR_QUESTION`
    * `YOUR_ANSWER`
8. (first run) Do the following to run it interactively to start, as you'll need to input a PIN (check Telegram):
    1. Copy the lines from `config.env` and add `export` to the start of them, and then run them.
    2. Run `python3 -m main.py`
    3. Enter the PIN in Telegram into the console window.
    4. Once confirmed it is running without errors, close it with `CTRL + C`
9. Copy the included `telegram-antispam.service` to `/etc/systemd/system` and edit the paths (`ExecStart` and `EnvironmentFile`) pointing to where `main.py` and `config.env` are also change `User` to the desired user account the service should run as.
10. Enable and run the service:
    ```
    sudo systemctl enable telegram-antispam
    sudo systemctl start telegram-antispam
    ```
11. View the logs in gcloud and using `journalctl -f -u telegram-antispam` on the VM, should be no errors.
