// Run with: node scripts/test_signup_app_return.cjs
// Execute the actual inline signup script with a small DOM and mocked HTTP.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const template = fs.readFileSync('templates/pages/auth/register.html', 'utf8');
const script = template.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const callback = 'myqrmenu://register-complete?email=plus%2Bsignup%40example.com';
const flush = () => new Promise(resolve => setImmediate(resolve));

function page(fromApp, pendingEmail = '', blockLaunch = false) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      const classes = new Set(['step-verify', 'step-success'].includes(id) ? ['hidden'] : []);
      elements.set(id, {
        value: id === 'email_verification_code' ? '123456' : '', textContent: '',
        dataset: {}, disabled: false, href: '#', handlers: {},
        classList: {add: x => classes.add(x), remove: x => classes.delete(x),
          contains: x => classes.has(x), toggle: (x, on) => on ? classes.add(x) : classes.delete(x)},
        addEventListener(name, fn) { this.handlers[name] = fn; },
        setAttribute() {}, removeAttribute() {}, reset() {},
        elements: {namedItem: name => element(name)},
      });
    }
    return elements.get(id);
  }
  element('signup-pending-email').textContent = JSON.stringify(pendingEmail);
  const requests = [], redirects = [], replies = [];
  const location = {assign: url => {
    redirects.push(url);
    if (blockLaunch) throw new Error('Browser blocked automatic launch');
  }};
  const context = {
    document: {getElementById: element, querySelector: () => ({value: 'csrf'})},
    window: {location},
    FormData: class { get(name) { return name === 'cf-turnstile-response' ? 'fresh-token' : ''; } },
    turnstile: {reset() {}},
    fetch: async (url, options) => {
      requests.push(JSON.parse(options.body));
      assert.ok(replies.length, 'Unexpected request');
      const reply = replies.shift();
      return {ok: reply.ok, json: async () => reply.data};
    },
    setTimeout() { assert.fail('No timed redirect is allowed'); },
    setInterval() { assert.fail('No redirect loop is allowed'); },
  };
  vm.runInNewContext(script.replace('{{ signup_from_app|yesno:"true,false" }}', String(fromApp)), context);
  return {element, requests, redirects, replies, location,
    async submit(id, data, ok = true) {
      replies.push({data, ok});
      element(id).handlers.submit({preventDefault() {}});
      await flush();
    }};
}

(async () => {
  const app = page(true);
  await app.submit('register-form', {success: true, email_verification_required: true, email: 'plus+signup@example.com'});
  assert.equal(app.requests[0].source, 'app');
  assert.equal(app.redirects.length, 0);
  assert.ok(app.element('step-success').classList.contains('hidden'));
  await app.submit('verify-form', {success: false, message: 'Invalid code'}, false);
  assert.equal(app.redirects.length, 0);
  assert.equal(app.element('btn-verify').disabled, false);
  const completed = {success: true, app_return_url: callback};
  await app.submit('verify-form', completed);
  assert.equal(app.requests[1].source, 'app');
  assert.deepEqual(app.redirects, [callback]);
  assert.equal(app.element('app-return-link').href, callback);
  assert.equal(app.element('step-success').classList.contains('hidden'), false);
  await app.submit('verify-form', completed);
  assert.deepEqual(app.redirects, [callback], 'Only one automatic launch per page');

  const resumed = page(true, 'plus+signup@example.com');
  assert.equal(resumed.element('step-verify').classList.contains('hidden'), false);
  assert.equal(resumed.element('verify-email-display').textContent, 'plus+signup@example.com');
  assert.equal(resumed.redirects.length, 0);
  await resumed.submit('verify-form', completed);
  assert.equal(resumed.requests[0].email, 'plus+signup@example.com');

  const blocked = page(true, 'plus+signup@example.com', true);
  await blocked.submit('verify-form', completed);
  assert.equal(blocked.element('app-return-link').href, callback);
  assert.equal(blocked.element('step-success').classList.contains('hidden'), false);
  await blocked.submit('verify-form', completed);
  assert.deepEqual(blocked.redirects, [callback]);

  const web = page(false);
  await web.submit('register-form', {success: true, email_verification_required: true, email: 'web@example.com'});
  await web.submit('verify-form', {success: true, panel_url: '/panel/?admin_id=1'});
  assert.equal(web.location.href, '/panel/?admin_id=1');
  assert.deepEqual(web.redirects, []);
  console.log('PASS: app success, manual fallback, retry, one launch, resumed verification, web signup');
})().catch(error => { console.error(error); process.exitCode = 1; });
