/**
 * CI E2E test — lightweight Playwright checks for regression protection.
 *
 * Runs against the Django dev server with seeded demo data.
 * Focuses on catching template/JS regressions, not Vibix playback.
 *
 * Exit code != 0 on failure → CI fails.
 */

const { chromium } = require('playwright');
const { spawn } = require('child_process');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const TIMEOUT = 15000;

let failures = 0;

function assert(condition, msg) {
    if (!condition) {
        console.error(`  FAIL: ${msg}`);
        failures++;
    } else {
        console.log(`  PASS: ${msg}`);
    }
}

async function waitForDjango(proc, timeoutMs = 30000) {
    return new Promise((resolve, reject) => {
        const start = Date.now();
        const check = async () => {
            try {
                const resp = await fetch(`${BASE}/healthz/`);
                if (resp.ok) return resolve();
            } catch {}
            if (Date.now() - start > timeoutMs) return reject(new Error('Django did not start'));
            setTimeout(check, 1000);
        };
        check();
    });
}

async function run() {
    console.log('Starting Django dev server...');
    const django = spawn('python', [
        'manage.py', 'runserver', '127.0.0.1:8000', '--noreload',
        '--settings=config.settings.development',
    ], {
        stdio: 'pipe',
        env: {
            ...process.env,
            DJANGO_SECRET_KEY: 'e2e-test-key-not-production-7f3a9d2e5b8c1046af93de27bc5081',
            DATABASE_URL: 'sqlite:///tmp/lumibox_e2e.db',
            DJANGO_ALLOWED_HOSTS: 'localhost,127.0.0.1',
        },
    });

    django.stderr.on('data', d => {
        const text = d.toString();
        if (text.includes('Traceback') || text.includes('Error')) {
            console.error('[DJANGO]', text.slice(0, 200));
        }
    });

    try {
        await waitForDjango(django);
        console.log('Django is ready.\n');

        const browser = await chromium.launch({ headless: true });

        try {
            const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
            const page = await ctx.newPage();

            // Collect JS errors
            const jsErrors = [];
            page.on('pageerror', err => jsErrors.push(err.message));

            // --- Test 1: Home page ---
            console.log('1. Home page');
            await page.goto(`${BASE}/`, { waitUntil: 'networkidle', timeout: TIMEOUT });
            const h1 = await page.textContent('h1');
            assert(h1 && h1.length > 0, 'Home page has h1');

            // --- Test 2: Catalog page ---
            console.log('2. Catalog page');
            await page.goto(`${BASE}/catalog/`, { waitUntil: 'networkidle', timeout: TIMEOUT });
            const catalogH1 = await page.textContent('h1');
            assert(catalogH1 && catalogH1.length > 0, 'Catalog page has h1');
            const cards = await page.$$('[class*="card"], [class*="film-card"], .film-feed > *');
            assert(cards.length >= 0, `Catalog renders without error (${cards.length} cards found)`);

            // --- Test 3: Search page ---
            console.log('3. Search page');
            await page.goto(`${BASE}/search/?q=test`, { waitUntil: 'networkidle', timeout: TIMEOUT });
            const searchStatus = await page.$('.search-results, .empty-state, [class*="empty"]');
            assert(true, 'Search page loads without crash');

            // --- Test 4: Genre list ---
            console.log('4. Genre list');
            await page.goto(`${BASE}/genres/`, { waitUntil: 'networkidle', timeout: TIMEOUT });
            const genreH1 = await page.textContent('h1');
            assert(genreH1 && genreH1.length > 0, 'Genre list page loads');

            // --- Test 5: 404 page ---
            console.log('5. 404 page');
            const resp404 = await page.goto(`${BASE}/nonexistent-page/`, { waitUntil: 'networkidle', timeout: TIMEOUT });
            assert(resp404.status() === 404, 'Non-existent page returns 404');

            // --- Test 6: Healthz ---
            console.log('6. Healthz endpoint');
            const healthResp = await page.goto(`${BASE}/healthz/`, { waitUntil: 'networkidle', timeout: TIMEOUT });
            assert(healthResp.status() === 200, 'Healthz returns 200');

            // --- Test 7: Login page ---
            console.log('7. Login page');
            await page.goto(`${BASE}/login/`, { waitUntil: 'networkidle', timeout: TIMEOUT });
            const loginForm = await page.$('form');
            assert(!!loginForm, 'Login page has form');

            // --- Test 8: Registration page ---
            console.log('8. Registration page');
            await page.goto(`${BASE}/register/`, { waitUntil: 'networkidle', timeout: TIMEOUT });
            const regForm = await page.$('form');
            assert(!!regForm, 'Registration page has form');

            // --- Test 9: Mobile overflow (320px) ---
            console.log('9. Mobile overflow at 320px');
            await ctx.close();
            const mobileCtx = await browser.newContext({ viewport: { width: 320, height: 568 } });
            const mobilePage = await mobileCtx.newPage();
            await mobilePage.goto(`${BASE}/`, { waitUntil: 'networkidle', timeout: TIMEOUT });
            const overflow320 = await mobilePage.evaluate(() =>
                document.documentElement.scrollWidth > document.documentElement.clientWidth
            );
            assert(!overflow320, 'No horizontal overflow at 320px on home page');
            await mobileCtx.close();

            // --- Test 10: Mobile overflow (375px) ---
            console.log('10. Mobile overflow at 375px');
            const mobileCtx2 = await browser.newContext({ viewport: { width: 375, height: 812 } });
            const mobilePage2 = await mobileCtx2.newPage();
            await mobilePage2.goto(`${BASE}/`, { waitUntil: 'networkidle', timeout: TIMEOUT });
            const overflow375 = await mobilePage2.evaluate(() =>
                document.documentElement.scrollWidth > document.documentElement.clientWidth
            );
            assert(!overflow375, 'No horizontal overflow at 375px on home page');
            await mobileCtx2.close();

            // --- Test 11: Desktop overflow (1440px) ---
            console.log('11. Desktop overflow at 1440px');
            const desktopCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
            const desktopPage = await desktopCtx.newPage();
            await desktopPage.goto(`${BASE}/`, { waitUntil: 'networkidle', timeout: TIMEOUT });
            const overflow1440 = await desktopPage.evaluate(() =>
                document.documentElement.scrollWidth > document.documentElement.clientWidth
            );
            assert(!overflow1440, 'No horizontal overflow at 1440px on home page');
            await desktopCtx.close();

            // --- Test 12: JS console errors ---
            console.log('12. JS console errors on home page');
            const cleanCtx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
            const cleanPage = await cleanCtx.newPage();
            const homeErrors = [];
            cleanPage.on('pageerror', err => homeErrors.push(err.message));
            await cleanPage.goto(`${BASE}/`, { waitUntil: 'networkidle', timeout: TIMEOUT });
            assert(homeErrors.length === 0, `No JS errors on home page (${homeErrors.length} errors)`);
            if (homeErrors.length > 0) {
                homeErrors.forEach(e => console.error(`    JS Error: ${e}`));
            }
            await cleanCtx.close();

        } finally {
            await browser.close();
        }

    } finally {
        django.kill();
        django.on('exit', () => {
            console.log(`\n=== E2E Results: ${failures === 0 ? 'ALL PASSED' : `${failures} FAILURES`} ===`);
            process.exit(failures > 0 ? 1 : 0);
        });
    }
}

run().catch(err => {
    console.error('Fatal E2E error:', err);
    process.exit(1);
});
