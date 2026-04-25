from __future__ import annotations

EFFECTIVE_DATE = "April 25, 2026"
CONTACT_EMAIL = "vincemartin1991@gmail.com"
COMPANY_NAME = "Antelope Labs"
PRODUCT_NAME = "Newsletter Pod"

_BASE_CSS = """
:root {
  --bg: #F5F0E6;
  --ink: #1C1A17;
  --muted: #6B6359;
  --accent: #B8642A;
  --rule: #D9D1C2;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 17px; line-height: 1.6; -webkit-font-smoothing: antialiased; }
.wrap { max-width: 720px; margin: 0 auto; padding: 56px 24px 96px; }
header { border-bottom: 1px solid var(--rule); padding-bottom: 24px; margin-bottom: 32px; }
.eyebrow { font-family: ui-serif, "New York", Georgia, serif; color: var(--accent);
  text-transform: uppercase; letter-spacing: 0.18em; font-size: 12px; font-weight: 600; }
h1 { font-family: ui-serif, "New York", Georgia, serif; font-weight: 700; font-size: 40px;
  line-height: 1.15; margin: 12px 0 8px; letter-spacing: -0.01em; }
h2 { font-family: ui-serif, "New York", Georgia, serif; font-weight: 600; font-size: 22px;
  margin: 36px 0 8px; }
h3 { font-size: 17px; font-weight: 600; margin: 24px 0 4px; }
.meta { color: var(--muted); font-size: 14px; }
p, li { color: var(--ink); }
ul { padding-left: 20px; }
li { margin: 6px 0; }
a { color: var(--accent); text-decoration: none; border-bottom: 1px solid currentColor; }
a:hover { opacity: 0.8; }
hr { border: none; border-top: 1px solid var(--rule); margin: 40px 0; }
footer { color: var(--muted); font-size: 13px; margin-top: 48px;
  border-top: 1px solid var(--rule); padding-top: 20px; }
""".strip()


def _wrap(eyebrow: str, title: str, body_html: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — {PRODUCT_NAME}</title>
  <style>{_BASE_CSS}</style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="eyebrow">{eyebrow}</div>
      <h1>{title}</h1>
      <div class="meta">Effective {EFFECTIVE_DATE}</div>
    </header>
    {body_html}
    <footer>
      Questions? Contact <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>.<br>
      &copy; {COMPANY_NAME}. All rights reserved.
    </footer>
  </div>
</body>
</html>"""


TERMS_HTML = _wrap(
    eyebrow="Legal",
    title="Terms of Use",
    body_html=f"""
<p>These Terms of Use (the &ldquo;Terms&rdquo;) govern your use of the {PRODUCT_NAME}
mobile application and related services (collectively, the &ldquo;Service&rdquo;),
operated by {COMPANY_NAME}. By creating an account or using the Service, you
agree to these Terms.</p>

<h2>1. The Service</h2>
<p>{PRODUCT_NAME} converts written sources you select into a personalized
audio podcast feed delivered on a schedule you choose. The Service is provided
&ldquo;as is&rdquo; and may change over time.</p>

<h2>2. Eligibility and accounts</h2>
<p>You must be at least 13 years old to use the Service. You sign in with
Sign in with Apple. You are responsible for activity on your account and for
keeping your Apple ID secure.</p>

<h2>3. Subscriptions and billing</h2>
<p>The Service offers an optional auto-renewing subscription with monthly and
annual billing periods. The following terms apply to subscriptions purchased
through Apple:</p>
<ul>
  <li><strong>Length and price.</strong> Subscription length and price are
  shown in the app prior to purchase and confirmed by Apple at checkout.</li>
  <li><strong>Auto-renewal.</strong> Your subscription renews automatically
  at the end of each billing period unless you cancel at least 24 hours before
  the end of the current period.</li>
  <li><strong>Payment.</strong> Payment is charged to your Apple ID account
  at confirmation of purchase and at each renewal.</li>
  <li><strong>Managing or canceling.</strong> You can manage or cancel your
  subscription at any time in <em>Settings &rarr; [your name] &rarr;
  Subscriptions</em> on your Apple device. Deleting the app does not cancel
  the subscription.</li>
  <li><strong>Refunds.</strong> Refunds are handled by Apple under its
  standard policies.</li>
</ul>

<h2>4. Sources and content</h2>
<p>You choose the sources used to generate your feed, including any custom
RSS URLs. You represent that you have the right to use those sources for
personal listening. The Service is for personal, non-commercial use; you may
not redistribute generated audio.</p>

<h2>5. Acceptable use</h2>
<ul>
  <li>Do not use the Service to infringe copyrights or other rights.</li>
  <li>Do not attempt to access another user&rsquo;s feed or account.</li>
  <li>Do not abuse, reverse engineer, or attempt to disrupt the Service.</li>
</ul>

<h2>6. Intellectual property</h2>
<p>The Service, including its software, design, and trademarks, is owned by
{COMPANY_NAME}. Audio generated for you is licensed to you for personal use
only. Source content remains the property of its respective owners.</p>

<h2>7. Termination</h2>
<p>You may stop using the Service and request account deletion at any time
by contacting <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>. We may
suspend or terminate accounts that violate these Terms.</p>

<h2>8. Disclaimers</h2>
<p>The Service is provided without warranties of any kind. Generated audio
is produced by automated systems and may contain errors or omissions. Do not
rely on the Service for critical decisions.</p>

<h2>9. Limitation of liability</h2>
<p>To the maximum extent permitted by law, {COMPANY_NAME} is not liable for
any indirect, incidental, or consequential damages arising from your use of
the Service. Our total liability for any claim is limited to the amount you
paid in the twelve months preceding the claim.</p>

<h2>10. Changes</h2>
<p>We may update these Terms. Material changes will be reflected by the
&ldquo;Effective&rdquo; date above. Continued use of the Service after a
change constitutes acceptance.</p>

<h2>11. Governing law</h2>
<p>These Terms are governed by the laws of the jurisdiction in which
{COMPANY_NAME} is established, without regard to conflict-of-laws rules.</p>

<h2>12. Contact</h2>
<p>For questions about these Terms, email
<a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>.</p>
""",
)


PRIVACY_HTML = _wrap(
    eyebrow="Legal",
    title="Privacy Policy",
    body_html=f"""
<p>This Privacy Policy explains what data {COMPANY_NAME} collects when you
use the {PRODUCT_NAME} mobile application and related services (the
&ldquo;Service&rdquo;), how we use it, and the choices you have.</p>

<h2>Information we collect</h2>

<h3>Account information</h3>
<p>When you sign in with Sign in with Apple, we receive a stable user
identifier from Apple and, if you choose to share it, your email address. We
do not receive your name or other Apple ID details unless you provide them.</p>

<h3>Content you provide</h3>
<p>We store the configuration you create in the app: podcast title, format,
host names, delivery schedule, and the catalog or custom RSS sources you
select.</p>

<h3>Generated content</h3>
<p>We store the audio episodes generated for your private feed and metadata
about each generation run.</p>

<h3>Diagnostic and usage data</h3>
<p>We log basic operational data such as request timestamps, error events,
and feed access events to operate and debug the Service. We do not use
third-party advertising or analytics SDKs.</p>

<h3>Subscription data</h3>
<p>If you subscribe to a paid plan, Apple processes your payment and shares
limited transaction information with us (such as the product purchased and
subscription status) so we can apply the correct entitlements. We do not
receive your payment card details.</p>

<h2>How we use information</h2>
<ul>
  <li>To generate and deliver your personalized podcast feed.</li>
  <li>To operate, maintain, and improve the Service.</li>
  <li>To apply the entitlements associated with your subscription.</li>
  <li>To respond to support requests.</li>
  <li>To detect and prevent abuse.</li>
</ul>

<h2>Third parties</h2>
<ul>
  <li><strong>Apple</strong> &mdash; Sign in with Apple, in-app purchases,
  and App Store delivery.</li>
  <li><strong>OpenAI</strong> &mdash; we send source text and generation
  prompts to OpenAI to produce episode scripts and audio. OpenAI processes
  this data under its API terms.</li>
  <li><strong>Google Cloud</strong> &mdash; we use Google Cloud services
  (Cloud Run, Firestore, Cloud Storage) to host the Service and store your
  data.</li>
</ul>
<p>We do not sell your personal information.</p>

<h2>Your private feed URL</h2>
<p>Your podcast feed is served at a URL containing a long random token. Treat
this URL as a secret &mdash; anyone who has it can listen to your feed. You
can request a new feed token by contacting support.</p>

<h2>Data retention</h2>
<p>We retain your account data while your account is active. Generated
episodes are retained according to a rolling window so that recent episodes
remain available in your podcast app. You can request deletion of your
account and associated data at any time by emailing
<a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>.</p>

<h2>Your choices and rights</h2>
<ul>
  <li><strong>Access and deletion.</strong> Email
  <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a> to request a copy of
  your data or to delete your account.</li>
  <li><strong>Subscription.</strong> Manage or cancel your subscription in
  <em>Settings &rarr; [your name] &rarr; Subscriptions</em> on your Apple
  device.</li>
  <li><strong>Notifications.</strong> The app does not send marketing push
  notifications.</li>
</ul>

<h2>Children</h2>
<p>The Service is not directed to children under 13 and we do not knowingly
collect personal information from them.</p>

<h2>Security</h2>
<p>We use industry-standard measures to protect your data in transit and at
rest. No system is perfectly secure; please use a strong Apple ID password
and keep your devices updated.</p>

<h2>International users</h2>
<p>The Service is operated from infrastructure located in Europe and the
United States. By using the Service, you consent to the transfer of your
data to those locations.</p>

<h2>Changes to this policy</h2>
<p>We may update this Privacy Policy. Material changes will be reflected by
the &ldquo;Effective&rdquo; date above.</p>

<h2>Contact</h2>
<p>Questions about this policy? Email
<a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>.</p>
""",
)
