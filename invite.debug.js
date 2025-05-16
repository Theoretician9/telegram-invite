const { chromium } = require('playwright');
const path = require('path');

(async () => {
  // Параметры: телефон и имя канала (без @)
  const phoneRaw = process.argv[2];
  const channelUsername = process.argv[3];
  if (!phoneRaw || !channelUsername) {
    console.error('Usage: node invite.debug.js "+71234567890" "channel_username"');
    process.exit(1);
  }
  const phone = phoneRaw.replace(/[^\d]/g, '');

  // Загрузка состояния сессии
  const storageState = path.resolve(__dirname, 'storageState.json');
  // Запуск в headless режиме
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ storageState });
  const page = await context.newPage();

  async function step(name, fn) {
    console.log(`Step: ${name}`);
    try {
      await fn();
      await page.screenshot({ path: `debug-after-${name}.png`, fullPage: true });
    } catch (e) {
      console.error(`Error at step ${name}:`, e);
      await page.screenshot({ path: `debug-error-${name}.png`, fullPage: true });
      await browser.close();
      process.exit(1);
    }
  }

  // 1. Открываем Web Telegram
  await step('goto', async () => {
    const url = 'https://web.telegram.org';
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 120000 });
  });

  // 2. Закрываем возможное окно ошибки или ввод номера
  await step('dismiss-error', async () => {
    const okBtn = page.getByRole('button', { name: /OK|Dismiss|Next|Skip|I understand/i });
    if (await okBtn.count() > 0) {
      await okBtn.click({ force: true });
      await page.waitForTimeout(1000);
    }
  });

  // 3. Поиск и открытие канала по username через статический поиск на боковой панели
  await step('search-channel', async () => {
    // Ждем, пока появится список диалогов
    await page.waitForSelector('#dialogs', { timeout: 60000 }).catch(() => {});
    // Находим поле поиска на боковой панели
    const sidebarSearch = page.locator('input[placeholder="Search"]').first();
    await sidebarSearch.waitFor({ state: 'visible', timeout: 60000 });
    await sidebarSearch.click({ force: true });
    await sidebarSearch.fill(channelUsername);
    // Ждем результатов и нажимаем Enter для открытия первого совпадения
    await page.waitForTimeout(1000);
    await sidebarSearch.press('Enter');
    await page.waitForTimeout(3000);
  });

  // 4. Переходим в редактирование канала
  await step('edit', async () => {
    const moreBtn = page.getByRole('button', { name: /More actions/i });
    await moreBtn.waitFor({ state: 'visible', timeout: 30000 });
    await moreBtn.click();
    const editMenu = page.getByRole('menuitem', { name: /Edit/i });
    await editMenu.waitFor({ state: 'visible', timeout: 10000 });
    await editMenu.click();
    await page.waitForTimeout(1000);
  });

  // 5. Открываем раздел Subscribers → Add users
  await step('open-add', async () => {
    const subsBtn = page.getByRole('button', { name: /Subscribers/i });
    await subsBtn.click();
    const addUsersBtn = page.getByRole('button', { name: /Add users/i });
    await addUsersBtn.click();
    await page.waitForTimeout(1000);
  });

  // 6. Ищем контакт по номеру
  await step('search', async () => {
    const addInput = page.getByRole('textbox', { name: /Add users/i });
    await addInput.click({ force: true });
    await addInput.fill(phone);
    await addInput.press('Enter');
    await page.waitForTimeout(1000);
  });

  // 7. Выбираем найденный контакт
  await step('choose-contact', async () => {
    const contactBtn = page.getByRole('button').filter({ hasText: phone }).first();
    if (await contactBtn.count() === 0) throw new Error(`Contact ${phone} not found`);
    await contactBtn.click({ force: true });
    await page.waitForTimeout(1000);
  });

  // 8. Подтверждаем добавление
  await step('confirm-add', async () => {
    const confirmBtn = page.getByRole('button', { name: /Add users/i });
    await confirmBtn.click();
    const doneBtn = page.getByRole('button', { name: /Done|OK/i });
    if (await doneBtn.count() > 0) {
      await doneBtn.click({ force: true });
      await page.waitForTimeout(1000);
    }
  });

  console.log('✅ Debug run completed successfully');
  await browser.close();
})();
	// 9. чё ты сука э