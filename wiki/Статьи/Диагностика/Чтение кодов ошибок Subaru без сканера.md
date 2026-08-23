---
type: статья
узел: диагностика
источников: 5
собрано: 2026-08-23
---

# Чтение кодов ошибок Subaru без сканера

Есть два разных способа снять коды ошибок без покупного сканера — они не взаимозаменяемы и рассчитаны на разные машины. Прежде чем лезть под панель или считать миганием лампы, определите, какой способ вообще подходит вашей машине.

## Способ 1. Через дисплей приборной панели (Legacy / Outback 2005–2009)

Работает на Subaru Legacy и Outback 2005–2009 годов выпуска [^f7]. Модельные годы вне этого диапазона в источнике не упоминаются — распространять способ на них нельзя.

Это альтернатива для тех, у кого нет перемычек-разъёмов «папа/мама» для замыкания диагностического разъёма [^f5]: коды ошибок можно увидеть прямо на trip-дисплее приборной панели вместо суточного пробега [^f6], и для этого не нужно никуда лезть и ничего физически соединять [^f8]. Коды выводятся обычным текстом на приборной панели — без сканера, без перемычек и без подсчёта миганий лампы [^f9]. Процедура распространяется сразу на три блока управления: ECM (двигатель), TCM (коробка передач) и ABSCM/VDCCM (ABS/VDC) [^f10]. Сама процедура взята из заводского руководства FSM, раздел Body Section → Instrument/Driver Information → Combination Meter System [^f11].

Автор полагает, что процедура работает на всех Legacy и Outback 2005–2009 годов, но лично проверял её только на своём Outback 2.5i 2007 года с автоматической коробкой [^f12]. Отдельно подтверждено владельцем, что она работает на Outback 2.5i 2007 года [^f13], а также на европейском Outback 2.5 АКПП 2006 модельного года [^f14].

То, что именно вы увидите на дисплее, зависит от типа приборной панели: для обычного дисплея и для Multi-Information Display (устанавливается на турбо-модели) — свои таблицы кодов [^f16].

### Порядок действий

Исходное состояние перед началом: зажигание выключено, выключатель фар выключен [^f17]. Шаги 1–7 нужно выполнить за 10 секунд [^f18].

1. Повернуть ключ в положение ON — щелчок перед стартером, когда загораются все лампы на панели, — но не заводить двигатель [^f19].
2. В течение 3 секунд включить ближний свет фар [^f20].
3. Нажать кнопку Trip/Odometer 4 раза [^f21].
4. Выключить ближний свет фар [^f22].
5. Снова нажать кнопку Trip/Odometer 4 раза [^f23].
6. Снова включить ближний свет фар [^f24].
7. Нажать кнопку Trip/Odometer 4 раза — после этого начнётся отображение кодов ошибок [^f25].
8. Необязательный шаг: выключить фары — так дисплей легче читать на солнце, да и незачем сажать аккумулятор [^f26].

### Как читать показания

Коды отображаются по очереди для каждого блока — ECM, TCM, ABSCM/VDCCM, переключение между ними делается кнопкой Trip/Odometer; заявленное в FSM автоматическое переключение каждые 3 секунды у автора на практике не сработало [^f27]. Для каждого блока возможны три состояния индикации: приём данных (мигающая «P» или «C»), обнаруженный код («P» или «C» и 4 цифры) или отсутствие кодов («P» или «C» и «----») [^f28]. На машинах с механической коробкой коды TCM не отображаются вовсе — там остаётся мигающая «P»; у автора машина на автомате, но мигающая «P» осталась и там, — возможно, из-за того, что кодов по TCM просто не было [^f30]. Чтобы выйти из режима отображения, нужно вернуть ключ в положение OFF [^f31].

### Если не получается

Если на дисплее видно только «----» — это признак ошибки шины CAN: сеть автомобиля неисправна, и это придётся чинить в первую очередь, до всего остального [^f29].

Если завести двигатель, отображение кодов, по непроверенным сведениям, должно сохраняться, пока машина не тронется с места [^f32]. Также, по непроверенным сведениям, уже устранённые коды продолжают показываться, пока двигатель не будет запущен 3 раза [^f33]. Способа сбросить коды без сканера автор не знает; отключение аккумулятора может помочь, а может и нет [^f15].

## Способ 2. Через диагностический разъём (JDM Legacy B4 2003)

Этот способ обсуждался применительно к Subaru Legacy B4 2003 года, японского внутреннего рынка [^f4], и в источнике доведён только до отрывочных наблюдений — цельной процедуры «подать код — посчитать миганья» в нём нет.

Диагностический разъём на этой машине серого цвета, похож на разъём Nissan [^f3]. Из документации удалось найти только то, что 4 контакт 14 пинового разъёма — это вывод для запуска выдачи медленных кодов неисправностей блока управления двигателем [^f2]. Про то, какие ещё контакты нужно соединять, в найденном источнике ничего нет: один из участников лишь предполагает, что раз речь про 14 контактный разъём, то нужно искать зелёные и чёрные провода — но это его личная догадка, а не подтверждённая инструкция [^f1].

## Если нужен сканер

Если ни один из способов выше не подошёл: все леворукие (LHD) машины спокойно сканируются дешёвым китайским сканером ELM327 с Aliexpress (около 450 рублей), для работы с ним нужно Android-устройство [^f34].

## Сноски

[^f7]: «На Subaru Legacy и Outback 2005 - 2009 годов выпуска» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f5]: «Альтернативный или дополнительный способ, для тех у кого нет разъемов папа/мама» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f6]: «Тут пишут, что коды ошибок действительно можно увидеть на trip жк дисплее вместо суточного пробега.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f8]: «И для этого не надо никуда лезть и ничего соединять!» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f9]: «The 2005 thru 2009 model year Legacy and Outback can display Diagnostic Trouble Codes (DTCs) directly on the dashboard. No scan tool is needed. No jumper wires are required, and it is not necessary to count blinky lights. The codes are displayed in plain text on the instrument cluster.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f10]: «Trouble codes from the ECM (Engine Control Module), TCM (Transmission Control Module) and ABSCM/VDCCM (ABS or VDC Control Module) are displayed.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f11]: «This procedure was distilled from the FSM. The English translation in the FSM is not very good, so I have attempted to make it easier to follow. The FSM has this procedure in the Body Section, Instrument/Driver Information, Comination Meter System chapter.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f12]: «I believe this procedure will work for all 2005 to 2009 Legacys and Outbacks. However, I have only tested the procedure on my car, a 2007 Outback 2.5i automatic.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f13]: «Процедура точно работает на машине Outback 2.5i 2007 года (так пишет владелец)» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f14]: «И еще она точно работает на европейке Outback 2.5 АКПП 2006 модельного года» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f16]: «Exactly what you will see depends on what type of display your car has. There are two images of tables below, one for the Normal display and one for the Multi-Information Display that is found on Turbo models.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f17]: «Starting condition: key off, headlight switch off.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f18]: «Steps 1 through 7 must be performed within 10 seconds.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f19]: «1. Turn key to ON position. This is the normal running position, the click just before starting, when all the lights on the dash come on, but before you twist to START. Don't start the engine!» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f20]: «2. Within 3 seconds, turn the headlight switch ON.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f21]: «3. Press the Trip/Odometer button 4 times.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f22]: «4. Turn the headlight switch OFF.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f23]: «5. Press the Trip/Odometer button 4 times.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f24]: «6. Turn headlight swtich ON.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f25]: «7. Press Trip/Odometer button 4 times. At this point, the DTC display will begin.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f26]: «8. Turn headlight switch OFF. Not necessary for the procedure, but your display may be dimmed and hard to read in bright sunlight. Besides, why drain the battery?» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f27]: «The DTCs for each module will display in order: ECM, TCM, ABSCM/VDCCM. Press the Trip/Odometer button to cycle between modules. The FSM states that the display will cycle between modules automatically every three seconds if the button is not pushed, but that did not happen in my car - I had to push the button to cycle the display.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f28]: «For each module, there are three display states: - Receiving DTC from module (blinking "P" or "C") - DTC detected & displayed ("P" or "C" followed by 4 digits) - No DTC found ("P" or "C" followed by "----")» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f30]: «TCM error codes will not be displayed for cars with manual transmissions. The TCM display state will remain in "Receiving DTC" (blinking "P" on display). In my case, my car is an automatic, but the blinking "P" remained, possibly because I have no codes set.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f31]: «To cancel the DTC display, turn the key to OFF.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f29]: «If there is a CAN (Controller Area Network) bus communication error, you will see only "----" in the display. Basically, that means that the network in your car is broken. That will need to be repaired before anything else can be done.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f32]: «If the engine is started, the DTC display will remain until the car starts to move. (I did not test this)» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f33]: «Past DTCs that have been repaired will be displayed until the engine is started 3 times. (I did not test this)» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f15]: «I don't know of a way to reset the codes without a scan tool. Disconnecting the battery may or may not work.» — Viktor, 20.04.2010, [[Тема 28899#Пост 219647]]
[^f4]: «субару легази, б-4, 2003 год, японец.» — Соколов, 29.05.2011, [[Тема 33495#Пост 268023]]
[^f3]: «Разъём серый, как у ниссана.» — Соколов, 29.05.2011, [[Тема 33495#Пост 268018]]
[^f2]: «Нашол только, что 4 контакт 14 пинового разъёма, вывод для запуска выдачи медленных кодов неисправностей блока управления двигателем.» — Соколов, 29.05.2011, [[Тема 33495#Пост 268017]]
[^f1]: «про 14 контактный разъём там ни слова, или при таком разъёме нужно искать зелёные и чёрные.» — Соколов, 29.05.2011, [[Тема 33495#Пост 268017]]
[^f34]: «Все леворукие машины спокойно сканируются китайским сканером елм327 с алиэкспресса. цена его 450р. нужен андроид-устройство.» — Ярослав, 06.07.2016, [[Тема 28899#Пост 408882]]
