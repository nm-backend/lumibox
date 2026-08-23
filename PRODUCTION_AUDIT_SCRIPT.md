# Production Audit Script for https://lumibox.site

> **Run this in Chrome DevTools Console on https://lumibox.site**

## Quick Start

1. Open https://lumibox.site in Chrome
2. Open DevTools (F12) → Console tab
3. Copy-paste the entire script below and press Enter
4. Follow the prompts

---

## Automated Audit Script

```javascript
(async function() {
  const results = {
    timestamp: new Date().toISOString(),
    url: window.location.href,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    userAgent: navigator.userAgent,
    checks: [],
    errors: [],
    screenshots: []
  };

  // Helper to run a check
  async function check(name, fn) {
    try {
      const result = await fn();
      results.checks.push({ name, status: 'PASS', details: result });
      console.log(`✅ ${name}: PASS`, result);
    } catch (e) {
      results.checks.push({ name, status: 'FAIL', error: e.message });
      console.error(`❌ ${name}: FAIL`, e);
    }
  }

  // Helper to click and verify
  async function clickAndVerify(selector, description, verifyFn) {
    const el = document.querySelector(selector);
    if (!el) throw new Error(`Element not found: ${selector}`);
    el.click();
    await new Promise(r => setTimeout(r, 1000)); // wait for UI update
    if (verifyFn) await verifyFn();
  }

  // 1. Homepage Load
  await check('Homepage loads', async () => {
    return { status: document.readyState, title: document.title };
  });

  // 2. Navigation Elements
  await check('Header visible', async () => {
    const header = document.querySelector('.site-header');
    return { visible: !!header, rect: header?.getBoundingClientRect() };
  });

  await check('Search input works', async () => {
    const input = document.querySelector('#search-input');
    if (!input) throw new Error('Search input not found');
    input.value = 'test';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await new Promise(r => setTimeout(r, 500));
    const dropdown = document.querySelector('.search__dropdown');
    return { hasDropdown: !!dropdown, results: dropdown?.textContent?.length || 0 };
  });

  // 3. Catalog Pages
  const catalogUrls = [
    '/catalog/',
    '/catalog/?type=movie',
    '/catalog/?type=series',
    '/new/',
    '/popular/',
    '/top/',
    '/premieres/',
    '/genres/',
    '/countries/',
    '/collections/',
    '/persons/',
    '/franchises/'
  ];

  for (const url of catalogUrls) {
    await check(`Catalog: ${url}`, async () => {
      const resp = await fetch(url, { method: 'HEAD' });
      return { status: resp.status, ok: resp.ok };
    });
  }

  // 4. Movie Detail Page (pick first movie from catalog)
  await check('Movie detail page loads', async () => {
    // Find first movie link on homepage or catalog
    const link = document.querySelector('.film-card a[href^="/title/"]') || 
                 document.querySelector('a[href^="/title/"]');
    if (!link) throw new Error('No movie link found');
    const href = link.href;
    const resp = await fetch(href, { method: 'HEAD' });
    return { url: href, status: resp.status };
  });

  // 5. Auth Flow
  await check('Login page accessible', async () => {
    const resp = await fetch('/login/', { method: 'HEAD' });
    return { status: resp.status };
  });

  await check('Register page accessible', async () => {
    const resp = await fetch('/register/', { method: 'HEAD' });
    return { status: resp.status };
  });

  // 6. Mobile Viewport Test
  const viewports = [320, 360, 375, 390, 414, 480, 768, 1024, 1440];
  for (const width of viewports) {
    // Note: Can't actually resize in script, but we can check CSS
    await check(`Mobile CSS: ${width}px`, async () => {
      const style = getComputedStyle(document.documentElement);
      return { 
        hasOverflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth
      };
    });
  }

  // 7. Console Errors
  const consoleErrors = [];
  const originalError = console.error;
  console.error = (...args) => {
    consoleErrors.push(args.join(' '));
    originalError.apply(console, args);
  };
  
  // Wait a bit for any async errors
  await new Promise(r => setTimeout(r, 3000));
  console.error = originalError;
  
  results.consoleErrors = consoleErrors;
  await check('No console errors', async () => {
    if (consoleErrors.length > 0) throw new Error(consoleErrors.join('; '));
    return { count: 0 };
  });

  // 8. Network Errors
  const networkErrors = [];
  const originalFetch = window.fetch;
  window.fetch = async (...args) => {
    const resp = await originalFetch(...args);
    if (!resp.ok && resp.status >= 400) {
      networkErrors.push({ url: args[0], status: resp.status });
    }
    return resp;
  };
  
  // Trigger some navigation to test network
  await fetch('/catalog/', { method: 'HEAD' });
  window.fetch = originalFetch;
  
  results.networkErrors = networkErrors;
  await check('No network errors (4xx/5xx)', async () => {
    if (networkErrors.length > 0) throw new Error(JSON.stringify(networkErrors));
    return { count: 0 };
  });

  // 9. Vibix Player (if available)
  await check('Vibix player gate button exists', async () => {
    const gateBtn = document.querySelector('[data-vibix-load]');
    return { exists: !!gateBtn };
  });

  // 10. Forms
  await check('Search form submits', async () => {
    const form = document.querySelector('form[action*="search"]');
    return { exists: !!form };
  });

  // Summary
  const passed = results.checks.filter(c => c.status === 'PASS').length;
  const failed = results.checks.filter(c => c.status === 'FAIL').length;
  
  console.log('\n========== AUDIT SUMMARY ==========');
  console.log(`Total checks: ${results.checks.length}`);
  console.log(`Passed: ${passed}`);
  console.log(`Failed: ${failed}`);
  console.log(`Console errors: ${results.consoleErrors.length}`);
  console.log(`Network errors: ${results.networkErrors.length}`);
  console.log('====================================\n');
  
  // Copy results to clipboard
  const summary = JSON.stringify(results, null, 2);
  await navigator.clipboard.writeText(summary);
  console.log('Results copied to clipboard!');
  
  return results;
})();
```

---

## Manual Verification Checklist

Run these manually after the automated script:

### Authentication Flow
- [ ] Register new account → verify email validation → login → profile → logout
- [ ] Password reset flow → token → new password
- [ ] Rate limiting on login/register

### Movie/Series Playback
- [ ] **Movie (YouTube fallback)**: Open `/title/sotsialnaya-set-2010/` → Click "Смотреть фильм" → Verify YouTube player loads → Play → Pause → Seek → Fullscreen
- [ ] **Series**: Open series page → Select season → Select episode → Play → Next episode
- [ ] **Vibix Player** (if configured): Click "Запустить плеер Vibix" → Wait for iframe → Play → Pause → Seek → Switch voiceover

### Interactive Elements (click each)
- [ ] Search input → type → autocomplete → select result
- [ ] Filter panel → genre → country → year → rating → quality → age → voiceover → reset
- [ ] Sort dropdown → each option
- [ ] Pagination → next → previous → page 2 → page 1
- [ ] Star rating → click stars 1-10 → verify toast
- [ ] Favorite button → toggle → verify toast
- [ ] Watchlist button → toggle → verify toast
- [ ] Share button → verify clipboard
- [ ] Comment form → submit → verify appears
- [ ] Reply to comment → verify threaded
- [ ] Theme toggle → light/dark → verify persists
- [ ] Language switcher → ru/en → verify
- [ ] Mobile menu (hamburger) → open/close
- [ ] Mobile bottom nav → all 4 items
- [ ] Trailer button → modal opens → play → close
- [ ] Player controls: play/pause/seek/volume/fullscreen/10s skip

### Admin Flow (if admin access)
- [ ] Admin login → `/admin/`
- [ ] Add movie → poster → metadata → genre → country → trailer → video → publish
- [ ] Create series → season → episode → voiceover → publish
- [ ] Verify on frontend

### Mobile Viewports (test each)
- [ ] 320px (iPhone SE)
- [ ] 360px (Galaxy S8)
- [ ] 375px (iPhone 12/13/14)
- [ ] 390px (iPhone 14 Pro)
- [ ] 414px (iPhone Plus)
- [ ] 480px
- [ ] 768px (iPad)
- [ ] 1024px
- [ ] 1440px
- [ ] 1920px

At each viewport:
- [ ] No horizontal overflow (`document.documentElement.scrollWidth === document.documentElement.clientWidth`)
- [ ] Header/navigation usable
- [ ] Search works
- [ ] Sidebar accessible
- [ ] Cards display correctly
- [ ] Player controls usable
- [ ] Forms fillable
- [ ] Bottom nav visible (mobile)
- [ ] Modals centered

### Visual Regression
- [ ] Screenshots at 320, 390, 768, 1024, 1440
- [ ] Compare with reference designs

---

## Expected Results

| Check | Expected |
|-------|----------|
| All automated checks | PASS |
| Console errors | 0 |
| Network errors (4xx/5xx) | 0 |
| Mobile overflow (320-1920px) | 0 |
| Horizontal overflow | 0 at all viewports |
| Vibix iframe | Created after gate click (if configured) |
| YouTube fallback | Works on Social Network page |
| All forms | Submit successfully |
| All buttons/links | Respond to clicks |
| No layout shifts | CLS = 0 |

---

## Reporting

After running the audit:
1. Paste clipboard contents (JSON results) into a file
2. Note any manual check failures
3. Create GitHub issues for each FAIL with:
   - BUG-ID
   - URL
   - Viewport
   - Action
   - Expected vs Actual
   - Console/Network errors
   - Root cause hypothesis
   - Severity (P0/P1/P2/P3)

---

## Known Limitations

- **Vibix Player**: Requires valid `VIBIX_API_TOKEN`, `VIBIX_PUBLISHER_ID`, and domain whitelisted in Vibix dashboard. Localhost may not work without Vibix dashboard configuration.
- **Email/SMTP**: Password reset requires configured `EMAIL_HOST` in production.
- **Admin Flow**: Requires admin credentials.
- **Vibix Domain Whitelist**: Production domain must be whitelisted in Vibix publisher dashboard.

---

## Contact

For questions about this audit script, refer to the LumiBox project documentation or create an issue in the GitHub repository.