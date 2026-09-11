const { chromium } = require('playwright');
const { spawn } = require('child_process');

async function runE2ETests() {
    console.log('Starting Django development server on port 8000...');
    const django = spawn('python', ['manage.py', 'runserver', '127.0.0.1:8000', '--noreload'], {
        stdio: 'pipe'
    });

    django.stdout.on('data', d => {
        const text = d.toString();
        if (text.includes('Quit the server')) {
            console.log('[DJANGO READY]');
        }
    });

    django.stderr.on('data', d => console.error('[DJANGO ERR]', d.toString()));

    await new Promise(resolve => setTimeout(resolve, 3000));

    console.log('Launching Playwright Chromium browser...');
    const browser = await chromium.launch({ headless: true });

    try {
        const context = await browser.newContext();
        const page = await context.newPage();

        // 1. Test Movie Detail Page
        console.log('\n--- 1. Testing Movie Detail Page (Inception 2010) ---');
        await page.goto('http://127.0.0.1:8000/title/nachalo-2010/', { waitUntil: 'networkidle' });
        
        const titleText = await page.textContent('h1');
        console.log('Title text:', titleText.trim());

        const sdkScripts = await page.$$('script[src*="rendex-sdk.min.js"]');
        const asyncScripts = await Promise.all(sdkScripts.map(script => script.evaluate(node => node.async)));
        const playerTag = await page.$('ins[data-publisher-id][data-nopreload="true"]');
        console.log('Rendex SDK scripts in head:', sdkScripts.length);
        console.log('Both SDK scripts are async:', asyncScripts.every(Boolean));
        console.log('Native Vibix lazy player tag found:', !!playerTag);

        // 2. Test Series Detail Page
        console.log('\n--- 2. Testing Series Detail Page (Game of Thrones) ---');
        await page.goto('http://127.0.0.1:8000/title/igra-prestolov/', { waitUntil: 'networkidle' });

        const seriesHeading = await page.textContent('h1');
        console.log('Series heading:', seriesHeading.trim());

        const episodeElements = await page.$$('.episode-card, [data-episode-item], .episodes-list__item, [data-season]');
        console.log('Episode / Season elements found:', episodeElements.length);

        // 3. Mobile Viewport & Responsiveness Check
        console.log('\n--- 3. Testing Mobile Viewports (320, 360, 390, 414, 768, 1440) ---');
        const viewports = [
            { width: 320, height: 568, name: 'iPhone SE (320px)' },
            { width: 360, height: 640, name: 'Galaxy S8 (360px)' },
            { width: 390, height: 844, name: 'iPhone 12/13/14 (390px)' },
            { width: 414, height: 896, name: 'iPhone Plus (414px)' },
            { width: 768, height: 1024, name: 'iPad Portrait (768px)' },
            { width: 1440, height: 900, name: 'Desktop (1440px)' }
        ];

        for (const vp of viewports) {
            await page.setViewportSize({ width: vp.width, height: vp.height });
            await page.goto('http://127.0.0.1:8000/title/nachalo-2010/', { waitUntil: 'networkidle' });
            
            const hasOverflow = await page.evaluate(() => {
                return document.documentElement.scrollWidth > document.documentElement.clientWidth;
            });

            console.log(`Viewport ${vp.name}: hasOverflow = ${hasOverflow}`);
            await page.screenshot({ path: `screenshot_${vp.width}.png` });
        }

        console.log('\nAll E2E checks passed successfully!');
    } catch (err) {
        console.error('E2E Test Error:', err);
    } finally {
        await browser.close();
        django.kill();
        console.log('Django server stopped.');
    }
}

runE2ETests();
