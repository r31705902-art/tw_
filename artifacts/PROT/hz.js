import puppeteer from 'puppeteer-extra';
import StealthPlugin from 'puppeteer-extra-plugin-stealth';
import fs from 'fs';
import path from 'path';

// Подключаем плагин маскировки (скрывает webdriver, подменяет Canvas, WebGL, языки и заголовки)
puppeteer.use(StealthPlugin());

// Функция генерации случайных строк
function generateRandomString(length) {
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let result = '';
  for (let i = 0; i < length; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return result;
}

// Заглушка для получения кода с почты
async function getEmailVerificationCodeStub(email) {
  console.log(`\n==================================================`);
  console.log(`[📩 ЗАГЛУШКА ПОЧТЫ] Код отправлен на: ${email}`);
  console.log(`[!] Сюда вы подключите ваше API почты (например, 1secmail / IMAP).`);
  console.log(`==================================================\n`);
  return null; 
}

(async () => {
  const username = `bot_${generateRandomString(12)}`;
  const password = `SuperPass_${generateRandomString(6)}!`;
  const email = `${generateRandomString(12)}@gmail.com`; // Замените на мыло из вашего API почт
  const dob = { day: '15', month: '5', year: '1998' };

  console.log(`\n[1/6] Запуск замаскированного браузера для создания аккаунта:`);
  console.log(`      Никнейм:  ${username}`);
  console.log(`      Пароль:   ${password}`);
  console.log(`      Email:    ${email}\n`);

  const accsDir = path.resolve('./accs');
  if (!fs.existsSync(accsDir)) {
    fs.mkdirSync(accsDir, { recursive: true });
  }

// Запуск браузера с правильными флагами и языковыми параметрами
  const browser = await puppeteer.launch({
    headless: false,
    defaultViewport: null,
    // executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', // Раскомментируйте, если хотите использовать установленный Chrome
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--lang=en-US,en', // Устанавливаем системный язык браузера
      '--window-size=1280,800',
      '--disable-web-security',
      '--disable-features=IsolateOrigins,site-per-process'
    ]
  });

  try {
    const page = await browser.newPage();

    // 1. Устанавливаем актуальный User-Agent (Chrome 126)
    const customUA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36';
    await page.setUserAgent(customUA);

    // 2. Устанавливаем HTTP-заголовки Client Hints и Язык (en-US)
    await page.setExtraHTTPHeaders({
      'accept-language': 'en-US,en;q=0.9',
      'sec-ch-ua': '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
      'sec-ch-ua-mobile': '?0',
      'sec-ch-ua-platform': '"Windows"',
    });

    // 3. Синхронизируем JS-контекст браузера (Client Hints + Languages)
    await page.evaluateOnNewDocument(() => {
      // Подменяем navigator.languages
      Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en'],
      });

      // Подменяем Client Hints (navigator.userAgentData), чтобы соответствовать Chrome 126
      Object.defineProperty(navigator, 'userAgentData', {
        get: () => ({
          brands: [
            { brand: 'Not/A)Brand', version: '8' },
            { brand: 'Chromium', version: '126' },
            { brand: 'Google Chrome', version: '126' }
          ],
          mobile: false,
          platform: 'Windows',
          getHighEntropyValues: async () => ({
            architecture: 'x86',
            bitness: '64',
            model: '',
            platformVersion: '15.0.0',
            uaFullVersion: '126.0.6478.127'
          })
        })
      });

      // Включаем эмуляцию плагинов (Chrome PDF Viewer и т.д.)
      Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
      });
    });

    // 3. Переход на страницу регистрации
    console.log('[2/6] Переход на https://www.twitch.tv/signup...');
    await page.goto('https://www.twitch.tv/signup', { waitUntil: 'networkidle2' });

    // 4. Заполнение формы регистрации
    console.log('[3/6] Заполнение полей формы...');
    
    // Ввод Email
    await page.waitForSelector('#email-input', { timeout: 20000 });
    await page.click('#email-input');
    await page.type('#email-input', email, { delay: 50 });

    // Клик "Продолжить"
    await page.waitForSelector('button[data-a-target="passport-signup-button"]');
    await page.click('button[data-a-target="passport-signup-button"]');

    // Ввод Имени пользователя
    await page.waitForSelector('#signup-username', { timeout: 15000 });
    await page.click('#signup-username');
    await page.type('#signup-username', username, { delay: 50 });

    // Ввод Пароля
    await page.waitForSelector('#password-input', { timeout: 15000 });
    await page.click('#password-input');
    await page.type('#password-input', password, { delay: 50 });

    // Заполнение Даты Рождения
    await page.waitForSelector('select[data-a-target="birthday-date-input"]');
    await page.select('select[data-a-target="birthday-date-input"]', dob.day);

    await page.waitForSelector('select[data-a-target="birthday-month-select"]');
    await page.select('select[data-a-target="birthday-month-select"]', dob.month);

    await page.evaluate((yearVal) => {
      const selects = Array.from(document.querySelectorAll('select'));
      const yearSelect = selects.find(s => s.getAttribute('aria-label')?.includes('год') || s.querySelector(`option[value="${yearVal}"]`));
      if (yearSelect) {
        yearSelect.value = yearVal;
        yearSelect.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }, dob.year);

    // 5. Клик "Зарегистрироваться"
    console.log('[4/6] Отправка формы регистрации...');
    await page.waitForSelector('button[type="submit"]');
    await page.click('button[type="submit"]');

    // 6. Ожидание ввода кода с почты (OTP)
    console.log('[5/6] Ожидание перехода на шаг ввода кода с почты...');
    
    // Если выскочит капча Arkose, решите её вручную в окне браузера!
    await page.waitForSelector('input[data-a-target="tw-input"]', { timeout: 60000 });

    const verificationCode = await getEmailVerificationCodeStub(email);

    if (verificationCode) {
      console.log(`[+] Вводим код из почты: ${verificationCode}`);
      await page.type('input[data-a-target="tw-input"]', verificationCode, { delay: 50 });
    } else {
      console.log('[!] Введите 6-значный код из вашей почты прямо в открывшееся окно браузера!');
    }

    // 7. Извлечение auth-token
    console.log('[6/6] Ожидание завершения авторизации и вытаскивания auth-token...');
    
    let authToken = null;
    const maxWaitTime = 60000;
    const startTime = Date.now();

    while (Date.now() - startTime < maxWaitTime) {
      const cookies = await page.cookies('https://www.twitch.tv');
      const authCookie = cookies.find(c => c.name === 'auth-token');
      
      if (authCookie && authCookie.value) {
        authToken = authCookie.value;
        break;
      }
      await new Promise(r => setTimeout(r, 1000));
    }

    if (!authToken) {
      throw new Error('Не удалось получить auth-token. Возможно, не был введен код с почты.');
    }

    // 8. Сохранение в JSON
    const accData = {
      username: username,
      password: password,
      email: email,
      authToken: authToken,
      createdAt: new Date().toISOString()
    };

    const filePath = path.join(accsDir, `${username}.json`);
    fs.writeFileSync(filePath, JSON.stringify(accData, null, 2), 'utf-8');

    console.log(`\n🎉 УСПЕХ! Аккаунт успешно создан:`);
    console.log(`💾 Файл сохранен: ${filePath}`);
    console.log(`🔑 Auth-Token: ${authToken}\n`);

    await browser.close();

  } catch (err) {
    console.error('\n[❌ ОШИБКА]:', err.message);
    await new Promise(r => setTimeout(r, 10000));
    await browser.close();
  }
})();