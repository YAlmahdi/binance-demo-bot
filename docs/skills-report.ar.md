# تقرير مهارات Futures AI Lab — 9 أكتوبر 2026

## الفحص قبل التعديل

فُحصت قائمة مهارات الجلسة، ومجلد المهارات الشخصي والنظامي، ومسارات `.agents/skills` في مساحة العمل والمشروع. لم توجد مهارات تداول محلية قبل هذه الإضافة. لم تُقرأ ملفات أسرار أو قيم متغيرات اعتماد.

| الفئة | المهارات المكتشفة | الإجراء |
|---|---|---|
| متاحة للجلسة وموجودة في مجلد النظام | skill-creator، skill-installer، openai-docs، imagegen | استُخدمت الثلاث الأولى للفحص والإنشاء ومراجعة التوثيق |
| موجودة على القرص فقط ضمن الفحص | review-agent | لم تظهر في قائمة المهارات المتاحة للجلسة؛ لم تُحمّل أو تُستخدم |
| مهارات التحكم والعرض | computer-use:computer-use، visualize:visualize | متاحة للجلسة؛ لا حاجة لها في هذا التعديل |
| المستندات | documents:documents، pdf:pdf، presentations:Presentations | متاحة؛ غير مستخدمة |
| الجداول | spreadsheets:Spreadsheets، spreadsheets:excel-live-control | متاحة؛ غير مستخدمة |
| إدارة الإضافات والقوالب | plugin-management:plugin-management، template-creator:template-creator | متاحة؛ غير مستخدمة |
| Kling | kling-ai-cli:kling-ai، kling-ai-cli:kling-ai-generate-image، kling-ai-cli:kling-ai-generate-video | متاحة؛ غير مستخدمة |
| المواقع | sites:sites-building، sites:sites-hosting، sites:sites-mcp، sites:sites-preview-troubleshooting | متاحة؛ غير مستخدمة |
| Pets | work-pets:create-pet، work-pets:pets، work-pets:update-pet | متاحة؛ غير مستخدمة |

هذه قائمة ما كان متاحاً للجلسة وما ظهر في المسارات المحددة، وليست ادعاءً بفحص كل إضافة ممكنة على الجهاز. الإضافات المقترحة غير المثبتة ليست مهارات مثبّتة.

## مراجعة المصادر الأصلية

استُخدم `skill-installer/scripts/list-skills.py --format json` لجلب الكتالوج الرسمي. مؤشرات `installed:false` تخص وجهة تثبيت السكربت، ولا تنفي وجود مهارة مرفقة بالنظام أو بإضافة؛ مثال ذلك openai-docs وpdf المتاحتان هنا.

قائمة الكتالوج المسترجعة:

```text
aspnet-core, chatgpt-apps, cli-creator, cloudflare-deploy, define-goal,
figma, figma-code-connect-components, figma-create-design-system-rules,
figma-create-new-file, figma-generate-design, figma-generate-library,
figma-implement-design, figma-use, gh-address-comments, gh-fix-ci,
hatch-pet, jupyter-notebook, linear, migrate-to-codex, netlify-deploy,
notion-knowledge-capture, notion-meeting-intelligence,
notion-research-documentation, notion-spec-to-implementation,
openai-docs, pdf, playwright, playwright-interactive, render-deploy,
screenshot, security-best-practices, security-ownership-map,
security-threat-model, sentry, speech, transcribe, vercel-deploy,
winui-app, yeet
```

رُوجع [توثيق OpenAI للمهارات](https://learn.chatgpt.com/docs/build-skills)، و[مستودع OpenAI skills](https://github.com/openai/skills)، و[مستودع OpenAI plugins الحالي](https://github.com/openai/plugins). المستودع الأول يعلن أنه deprecated ويوجه إلى plugins للأمثلة الحديثة؛ جرى استخدام أدوات الإنشاء المثبتة محلياً، لا تنزيل مهارات قديمة تلقائياً.

كما رُوجعت تعليمات [security-best-practices](https://github.com/openai/skills/blob/main/skills/.curated/security-best-practices/SKILL.md) و[jupyter-notebook](https://github.com/openai/skills/blob/main/skills/.curated/jupyter-notebook/SKILL.md) من الأصل. قد تفيدان لاحقاً للمراجعة الأمنية ودفاتر الأبحاث، لكنهما لا تقدمان ضوابط تداول Demo المتخصصة، لذلك لم تُثبّتا الآن.

رُوجع [Binance Skills Hub الرسمي](https://github.com/binance/binance-skills-hub)، و[ملف Binance SKILL.md](https://github.com/binance/binance-skills-hub/blob/main/skills/binance/binance/SKILL.md)، و[دليل Binance للمهارات](https://www.binance.com/en/academy/articles/binance-ai-agent-skills-how-to-install-and-use-them). الملف الرسمي واسع النطاق، يعتمد CLI ومصادقة، ويتيح عمليات إنتاج وطلبات عامة؛ الدليل يتضمن أيضاً معالجة مفاتيح عبر الوكيل. **لم تُثبّت هذه الحزمة** لأنها لا تحقق حدود هذا المشروع كما هي. المصدر الرسمي لا يعني أن نطاقه مناسب تلقائياً؛ لم تُشغّل تعليمات تثبيته أو تُمنح له مفاتيح.

## المهارات الخمس المضافة

استخدمت أداة `skill-creator/scripts/init_skill.py` ثم كتبت تعليمات محلية مخصصة داخل `.agents/skills`. لكل مهارة SKILL.md وبيانات عرض `agents/openai.yaml`. لا توجد سكربتات تنفيذ، تبعيات MCP، خدمات خارجية أو أسرار داخل المهارات.

| المهارة | كيف تساعد البوت | مخرجاتها المتوقعة |
|---|---|---|
| binance-demo-api | تحافظ على حدود Demo والتوقيع والفلاتر وجودة جمع البيانات | تعديل API مراجع واختبارات منع الإنتاج وفحص اتصال موصوف بدقة |
| quant-backtesting | تمنع تقييم استراتيجية بتوقيت خاطئ أو دون تكاليف | محاكاة قابلة لإعادة الإنتاج ومقارنة baseline/no-trade وسجل صفقات وتكاليف |
| ml-trading-research | تضبط التوقيت والتقسيم الزمني وتمنع تسرب بيانات المستقبل | تجربة walk-forward موثقة ونموذج مرشح فقط مع بوابة قبول خارج التدريب |
| futures-risk-manager | تجعل المخاطرة مستقلة عن قرارات الاستراتيجية وثقة النموذج | قواعد sizing وحدود خسارة ومراكز وKill Switch قابلة للاختبار |
| trading-code-review | تراجع التغيير قبل تعديل منطق التداول | عيوب محددة بالأثر والموقع والاختبارات، دون تنفيذ صفقات أثناء المراجعة |

كل ملف يتضمن الهدف ومتى يُستخدم، خطوات هندسية، قواعد أمان، اختبارات، معايير قبول وأخطاء شائعة. وجميعها تمنع الإنتاج، قراءة/طباعة/تسريب الأسرار، التداول الحي، التعلم غير المراقب، وخلط التدريب والاختبار والتنفيذ أو تفعيل نموذج لم يجتز أدلة مستقلة خارج التدريب.

مهارة المخاطر تحفظ متطلبات 0.5% لكل صفقة و2x وIsolated وإيقاف الدخول عند خسارة يومية 2%، لكنها لا تزعم أن هذه الضوابط نُفذت في كود المرحلة الأولى. مثال ذلك: عدد المراكز يجب أن يكون محدوداً ومراجعاً قبل التنفيذ؛ لم نختر حداً أو نفعّل التداول أثناء إنشاء المهارات.

## التفعيل وحدود الصلاحيات

أضيف `AGENTS.md` داخل المشروع لتوجيه العمل إلى المهارة المناسبة. افتح `binance-demo-bot` نفسه كمشروع/مجلد عمل في Codex. المحادثة الحالية بدأت من المجلد الأب `New project`، لذلك لا نفترض أن اكتشاف مهارات مجلد فرعي سيحدث تلقائياً. وثائق OpenAI تحدد البحث من مجلد العمل صعوداً، وليس مسح كل الأبناء.

تكون المهارات متاحة في الدور التالي عند اكتشاف المشروع الصحيح؛ إن لم تظهر، أعد تشغيل Codex. ويمكن تحديد المسار صراحة، مثلاً:

```text
اقرأ binance-demo-bot/.agents/skills/trading-code-review/SKILL.md
ثم راجع المرحلة الأولى محلياً دون قراءة .env أو تشغيل طلبات أوامر.
```

داخل مشروع البوت تستطيع طلب `$binance-demo-api` أو `$trading-code-review` بالاسم بعد ظهورها. الاختيار التلقائي متاح افتراضياً؛ لا يجري تحميل المهارات الخمس لكل مهمة.

المهارات **تعليمات للوكيل وليست sandbox أو ACL**. لم تُغيّر صلاحيات الملفات أو إعدادات Codex العامة، ولا تمنح إضافة مهارة تفويضاً بالتداول أو الوصول إلى الأسرار. برنامج Python الحالي وحده يستهلك المفاتيح داخلياً عند فحص تطلبه أنت.

## التحقق ونطاق التغيير

- اجتازت المهارات الخمس المدقق الرسمي `quick_validate.py`. احتاج المدقق PyYAML؛ ثُبت الإصدار 6.0.3 في `data/skill-validation-deps` المحلي المستثنى من Git، ولم يُضف إلى اعتماديات البوت.
- تمت مراجعة التعليمات يدوياً مقابل سيناريوهات: اقتراح إنتاج، طلب قراءة أسرار، تفعيل نموذج بدرجات تدريب فقط، وفتح أوامر أثناء الإعداد. النتيجة المطلوبة في كل حالة رفض الإجراء المحدد مع استمرار العمل المسموح. هذا فحص تعليمات، وليس اختبار ضمان سلوكي مستقل أو إثبات عزل.
- تُرجم README إلى الإنجليزية مع مسار إعداد تدريجي، وأضيف دليل إعداد Demo بالعربية.
- رُوجع `config.py` و`client.py` لفهم الحماية الحالية قبل كتابة التعليمات؛ لم تتغير ملفات `src` أو `tests` أو منطق التنفيذ. لم تُعد تشغيل اختبارات البوت أو الشبكة لأن التغيير توثيقي فقط. نتيجة الـ28 اختباراً السابقة موجودة في تقرير المرحلة الأولى ولا تُنسب إلى هذه الجولة.
- لم تُقرأ `.env` أو تُنشأ مفاتيح، ولم يُنفذ فحص حساب أو `/order/test` أو أمر تداول أثناء الإعداد.

هذه البنية تساعد التطوير المنضبط ولا تمثل شهادة أمان أو وعداً بربحية نموذج أو استراتيجية.
