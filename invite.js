// invite.js

const { chromium } = require('playwright');

(async () => {
  // 1) Запускаем headless-браузер
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    storageState: 'storageState.json'
  });

  // 2) Открываем Web-Telegram
  await page.goto('https://web.telegram.org/a/', {
    waitUntil: 'domcontentloaded',
    timeout: 60000
  });

  // 3) Входим в канал (форсим клики, чтобы обойти backdrop)
  await page.getByRole('button', { name: 'Test Invite bot Test Invite' }).click({ force: true });

  // 4) Edit → Subscribers → Add users
  await page.locator('#MiddleColumn #peer-story-1002503473511').getByText('T').click({ force: true });
  await page.getByRole('button', { name: 'Edit' }).click({ force: true });
  await page.getByRole('button', { name: 'Subscribers' }).click({ force: true });
  await page.getByRole('button', { name: 'Add users' }).click({ force: true });

  // 5) Вводим имя контакта (номер без '+') и Enter
  const phone = process.argv[2];
  const name = phone.replace(/^\+/, '');
  await page.getByRole('textbox', { name: 'Add users' }).fill(name);
  await page.getByRole('textbox', { name: 'Add users' }).press('Enter');

  // 6) Выбираем первый результат и подтверждаем
  const locator = page.getByText(new RegExp(`^${name}$`));
  await locator.first().click({ force: true });
  await page.getByRole('button', { name: 'Add users' }).click({ force: true });

  // 7) Ждём и выходим
  await page.waitForTimeout(500);
  await browser.close();
})();
