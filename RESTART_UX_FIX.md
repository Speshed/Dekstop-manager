# Исправление UX кнопки "Перезапуск бота" (Restart bot)

## Кратко, как теперь обрабатывается старый explorer UI при restart

**Механизм обработки:**

1. **При нажатии `Перезапуск бота`:**
   - Вызывается `start_command(update, context)` (строка 4048)
   - Функция сохраняет `old_explorer_message_id` и `old_explorer_chat_id` **до** очистки `user_data`

2. **Удаление или деактивация старого explorer-сообщения:**
   ```python
   # Пытаемся удалить сообщение
   await context.bot.delete_message(
       chat_id=old_explorer_chat_id,
       message_id=old_explorer_message_id
   )
   ```
   
3. **Если удаление не удалось (сообщение слишком старое/удалено):**
   - Пробуем убрать inline keyboard как fallback:
   ```python
   await context.bot.edit_message_reply_markup(
       chat_id=old_explorer_chat_id,
       message_id=old_explorer_message_id,
       reply_markup=None
   )
   ```
   - Это делает кнопки нефункциональными, нельзя кликнуть по ним.

4. **Очистка данных:**
   - `context.user_data.clear()` удаляет **все** данные,5. **Показ нового экрана:**
   - Отправляется welcome-сообщение
   - Устанавливается state = WAITING_FOR_LOGIN

## Какие поля context.user_data очищаются дополнительно

При `context.user_data.clear()` автоматически очищаются:

| Поле | Описание |
|------|----------|
| `explorer_message_id` | ID последнего explorer-сообщения |
| `explorer_chat_id` | Chat ID последнего explorer-сообщения |
| `path` | Текущий путь в дереве папок |
| `full_tree` | Полное дерево проекта |
| `file_names` | Кэш имён файлов |
| `project_id` | ID текущего проекта |
| `workspace_id` | ID текущего workspace |
| `workspace_name` | Название workspace |
| `subscriptions` | Подписки пользователя |
| `username` | Введённый логин (при логине) |
| `state` | Текущее состояние |
| `last_update_id` | ID последнего update (защита от дублей) |
| `api_client` | API клиент |
| и все остальные данные |

## Подтверждение, что restart теперь визуально понятен пользователю

**До исправления:**
- ❌ Старое explorer-меню остаётся на экране
- ❌ Welcome-сообщение появляется ниже
- ❌ Пользователь видит два меню одновременно
- ❌ Непонятно, работает бот или нет

**После исправления:**
- ✅ Старое explorer-меню **удаляется** (или деактивируется)
- ✅ Появляется **чистый** welcome-экран
- ✅ Пользователь видит **один** стартовый экран
- ✅ Очевидно, что сессия началась заново

**Проверка:**
1. ✅ Находясь в explorer, нажать `Перезапуск бота`
2. ✅ Старое explorer-меню исчезает или деактивируется
3. ✅ Появляется чистый стартовый экран
4. ✅ Бот ждёт новый логин
5. ✅ Старые inline-кнопки explorer не работают (удалены или неактивны)
