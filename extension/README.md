# job-bot browser extension

Fills job applications in your own Chrome with your job-bot packet: name, email,
phone, LinkedIn/GitHub, current company, and your tailored resume + cover letter
PDFs. Works on Greenhouse, Lever, Ashby and most other application forms,
including jobs you reach via Himalayas, The Muse, Jobicy or Adzuna.

It never submits, never navigates or clicks for you, and never answers
work-authorization, sponsorship, salary, EEO or other sensitive questions.
Fields that already have a value are left alone.

## Install (until it's on the Chrome Web Store)
1. Download `job-bot-extension.zip` from your job-bot site and unzip it.
2. Open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**,
   and choose the `job-bot-extension` folder.
3. Pin the job-bot icon, open job-bot **Settings**, click **Connect browser extension**.

## Use
On an application form, click the job-bot icon. It suggests the matching
prospect (★); click **Fill this application**, review everything, submit
yourself, then **Mark as applied**.

## How it's built
- `pair.js` runs only on the job-bot site and receives a connection key when
  you click Connect. The key can only list your prospects, download your
  packet files and mark jobs; disconnect revokes it. Only its hash is stored.
- `popup.js` fetches the packet and injects `fill.js` into the current tab
  (permission: the active tab, plus common application-form sites for forms
  embedded in company career pages).
- Tests: `tests/test_extension.py` runs `fill.js` against mock forms.
