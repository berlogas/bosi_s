import { Accordion, List, Text } from '@mantine/core'
import React from 'react'

interface HowToPanelProps {
  hasProjects: boolean
}

export function HowToPanel({ hasProjects }: HowToPanelProps) {
  return (
    <Accordion defaultValue="howto" multiple={false}>
      <Accordion.Item value="howto">
        <Accordion.Control>
          <Text size="sm" fw={600}>Как работать с проектом статьи</Text>
        </Accordion.Control>
        <Accordion.Panel>
          <List size="sm" spacing={2} mt={4}>
            <List.Item>
              Создайте проект и выберите стиль журнала — план разделов создастся сам: Введение, Методы исследования, Результаты, Обсуждение, Заключение. Промпт выбранной группы (роль, аудитория, структура раздела) подставляется в генерацию — его текст показан сразу под выбором стиля.
            </List.Item>
            <List.Item>
              Привяжите документы с ролью: <b>Литература</b> — для цитирования, <b>Данные</b> — ваши CSV (участвуют в сверке), <b>Черновик</b> — попадёт в контекст как есть.
            </List.Item>
            <List.Item>
              Раздел можно дописать руками или сгенерировать: модель использует контекст сессии и обязана ставить ссылки на источники. Каждая генерация сохраняется как версия — прошлый текст не пропадает.
            </List.Item>
            <List.Item>
              «Разбор черновика» покажет проблемы: число без ссылки, не написан обязательный раздел, есть результаты, но нет методики. Работает мгновенно, без обращения к модели.
            </List.Item>
            <List.Item>
              Готовую статью выгрузите внизу экрана: Word, Markdown или ZIP с библиографией и исходниками.
            </List.Item>
          </List>
          {!hasProjects && (
            <Text size="xs" c="dimmed" mt={4}>
              Начните с первого шага — поля «Название» и «Стиль журнала» слева.
            </Text>
          )}
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  )
}