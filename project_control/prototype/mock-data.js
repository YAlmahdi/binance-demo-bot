/* Single display fixture. All evidence, dates, identifiers and readiness are fictional. */
"use strict";
(() => {
  const fixture = {
  "schemaVersion": 3,
  "mock": true,
  "freshness": {
    "lastVerifiedUpdate": "2032-06-04T09:30:00Z",
    "sourceSha": "MOCK-SHA-NOT-A-COMMIT-V2",
    "localState": "Local",
    "publishedState": "Unverified",
    "note": "قيم تجريبية فقط؛ هذا التاريخ والمعرّف ليسا من Git أو من أدلة المشروع."
  },
  "health": [
    {
      "category": "Engineering",
      "status": "tested",
      "value": "Contract checks only",
      "description": "مثال خيالي: جزء من البنية له فحوص محددة، وليس البوت كاملًا.",
      "tested": "MOCK: فحوص وحدات خيالية لعقد replay مع مدخلات مصطنعة.",
      "missing": "ربط المكوّنات والتحقق من سيناريوهات فشل كاملة غير موجودين في المثال.",
      "blocked": "اعتماد النظام كاملًا ينتظر دليلًا أوسع ومراجعة مستقلة.",
      "limitations": "هذه ليست اختبارات نُفّذت. فحص عقد صغير لا يثبت أمان التشغيل أو الربحية."
    },
    {
      "category": "AI/ML",
      "status": "built",
      "value": "Unfitted interfaces",
      "description": "مثال خيالي: واجهات features جاهزة كفكرة، بدون نموذج مُدرّب.",
      "tested": "MOCK: أمثلة مصطنعة لفصل مدخلات features عن المخرجات.",
      "missing": "لا training أو calibration أو untouched evaluation في هذا السيناريو.",
      "blocked": "الانتقال للتقييم يحتاج بيانات وأدلة وصلاحية منفصلة؛ لا إذن هنا.",
      "limitations": "لا prediction accuracy معروضة، ووجود واجهة لا يثبت predictive value."
    },
    {
      "category": "Strategy",
      "status": "blocked",
      "value": "Baseline proposal",
      "description": "مثال خيالي: قواعد baseline مقترحة، لم تُعتمد كنظام قرارات.",
      "tested": "MOCK: أمثلة لتوضيح حدود القواعد فقط، بدون نتائج سوق.",
      "missing": "لا مقارنة مستقلة أو تحقق من قابلية التعميم.",
      "blocked": "اعتماد القواعد ينتظر مراجعة الأدلة؛ ليس مجرد نجاح software tests.",
      "limitations": "لا signals أو تداول أو ادعاء فعالية لاستراتيجية فعلية."
    },
    {
      "category": "Financial Performance",
      "status": "not_evaluated",
      "value": "Not Evaluated",
      "description": "مثال خيالي: لا أدلة مالية كافية لعرض استنتاج.",
      "tested": "MOCK: لا تحقق اقتصادي في القصة التجريبية.",
      "missing": "لا net PnL أو drawdown أو cost-aware evaluation معتمدة.",
      "blocked": "الاستنتاج المالي ينتظر أدلة مستقلة عن صحة الكود.",
      "limitations": "لا أرقام ربحية أو نتائج backtest؛ نجاح الهندسة لا يثبت الربح."
    },
    {
      "category": "Risk",
      "status": "not_cleared",
      "value": "Not Cleared",
      "description": "مثال خيالي: حاجز المخاطر مغلق، حتى لو نجح اختبار هندسي.",
      "tested": "MOCK: سيناريو رفض مصطنع، وليس اختبار تشغيل فعلي.",
      "missing": "التحقق المستقل من حدود الخسارة وسلوك الإخفاق غير متاح.",
      "blocked": "Trading readiness يبقى محجوبًا حتى مراجعة منفصلة؛ لا clearance هنا.",
      "limitations": "هذه حالة خيالية، ولا تمنح تصريحًا بحثيًا أو تشغيليًا."
    },
    {
      "category": "GitHub/Publication",
      "status": "unverified",
      "value": "Local / Unverified",
      "description": "مثال خيالي: نسخة محلية بلا إثبات نشر.",
      "tested": "MOCK: لا استعلام Git أو GitHub ولا تأكيد publication.",
      "missing": "لا published commit receipt أو مقارنة SHA فعلية.",
      "blocked": "النشر لا يمكن تأكيده من بيانات التصميم.",
      "limitations": "Source SHA معرّف وهمي صريح؛ لا يدل على commit موجود."
    }
  ],
  "roadmap": [
    {
      "id": "mock-foundation",
      "title": "Mock Harness Foundations",
      "phase": "Past Engineering",
      "status": "complete",
      "description": "عقود وحدات صغيرة؛ تفاصيل حدودها في المكوّن أدناه.",
      "readiness": {
        "built": "عقود وحدات معزولة.",
        "tested": "أمثلة مصطنعة للعقد فقط.",
        "missing": "تكامل شامل بين الوحدات.",
        "blocked": "مراجعة النظام لم تكتمل.",
        "next": "مراجعة حدود العقد."
      },
      "components": [
        {
          "title": "Contract Boundaries",
          "description": "المكوّن يحدد ما يقبله وما يرفضه.",
          "steps": [
            {
              "title": "Input shape",
              "status": "built",
              "description": "تعريف مدخلات خيالية واضحة."
            },
            {
              "title": "Rejection cases",
              "status": "tested",
              "description": "فحوص مصطنعة في القصة فقط."
            }
          ],
          "status": "tested"
        }
      ]
    },
    {
      "id": "mock-replay",
      "title": "Mock Replay Envelope",
      "phase": "Engineering",
      "status": "active",
      "description": "واجهة تربط النتيجة بدليلها؛ تفاصيل المكوّنات تبيّن ما لم يُبنَ بعد.",
      "readiness": {
        "built": "Result envelope أولي.",
        "tested": "Synthetic field checks فقط.",
        "missing": "Failure isolation وintegration.",
        "blocked": "دليل مسارات الفشل غير مكتمل.",
        "next": "Scoped contract review."
      },
      "components": [
        {
          "title": "Result Envelope",
          "description": "نعرف من أين جاءت النتيجة وما حدودها.",
          "steps": [
            {
              "title": "Evidence fields",
              "status": "built",
              "description": "حقول تفسير خيالية جاهزة."
            },
            {
              "title": "Failure isolation",
              "status": "missing",
              "description": "لم يُبنَ ربط الأخطاء بعد."
            }
          ],
          "status": "built"
        },
        {
          "title": "Verification Boundary",
          "description": "نفصل النجاح الهندسي عن النتائج المالية.",
          "steps": [
            {
              "title": "Synthetic rejection",
              "status": "tested",
              "description": "مثال اختباري خيالي محدود."
            },
            {
              "title": "Integration receipt",
              "status": "blocked",
              "description": "دليل التكامل غير متاح."
            },
            {
              "title": "Independent review",
              "status": "next",
              "description": "اقتراح للمراجعة قبل توسيع النطاق."
            }
          ],
          "status": "blocked"
        }
      ]
    },
    {
      "id": "mock-features",
      "title": "Mock Feature Sandbox",
      "phase": "Exploratory Research",
      "status": "blocked",
      "description": "استكشاف features دون افتراض نموذج صالح.",
      "readiness": {
        "built": "واجهات features تصوّرية.",
        "tested": "لا fitting أو تقييم تنبؤي.",
        "missing": "دليل data quality وcausality.",
        "blocked": "جاهزية البحث غير مثبتة.",
        "next": "تحديد أسئلة البحث ضمن موافقة."
      },
      "components": [
        {
          "title": "Feature Evidence",
          "description": "الواجهة وحدها لا تثبت جودة البيانات.",
          "steps": [
            {
              "title": "Causality review",
              "status": "missing",
              "description": "أدلة التوقيت غير متاحة."
            },
            {
              "title": "Research access gate",
              "status": "blocked",
              "description": "لا إذن أو تشغيل من النموذج."
            }
          ],
          "status": "blocked"
        }
      ]
    },
    {
      "id": "mock-validation",
      "title": "Mock Validation Gate",
      "phase": "Future Validation",
      "status": "planned",
      "description": "تصميم validation مستقل عن exploration؛ لا نتائج فعلية.",
      "readiness": {
        "built": "قائمة متطلبات مقترحة.",
        "tested": "لم تُنفّذ validation.",
        "missing": "Untouched evidence ومقارنات.",
        "blocked": "الدليل لا يكفي لاستنتاج.",
        "next": "اقتراح خطة مراجعة مستقلة."
      },
      "components": [
        {
          "title": "Validation Design",
          "description": "يحتاج الحكم على ML دليلًا مختلفًا عن اختبار الكود.",
          "steps": [
            {
              "title": "Untouched evaluation",
              "status": "missing",
              "description": "لا نتائج أو تقسيمات فعلية هنا."
            },
            {
              "title": "Baseline comparison",
              "status": "next",
              "description": "متطلب مستقبلي خيالي فقط."
            }
          ],
          "status": "missing"
        }
      ]
    },
    {
      "id": "mock-readiness",
      "title": "Mock Execution Gate",
      "phase": "Trading Readiness",
      "status": "approval",
      "description": "حاجز تشغيل تصوّري؛ لا تصريح للتداول.",
      "readiness": {
        "built": "وصف حاجز التشغيل فقط.",
        "tested": "لا اختبارات تشغيل أو أوامر.",
        "missing": "Operational safety evidence.",
        "blocked": "الدليل المالي وRisk غير معتمدين.",
        "next": "مراجعة منفصلة، دون تنفيذ."
      },
      "components": [
        {
          "title": "Operational Clearance",
          "description": "نجاح التطوير لا يفتح بوابة التشغيل.",
          "steps": [
            {
              "title": "Safety validation",
              "status": "blocked",
              "description": "الدليل غير مكتمل في المثال."
            },
            {
              "title": "Scoped approval",
              "status": "next",
              "description": "موافقة مستقلة مطلوبة، وغير ممنوحة."
            }
          ],
          "status": "blocked"
        }
      ]
    }
  ],
  "current": {
    "milestoneId": "mock-replay",
    "building": "في هذا المثال نبني envelope يرافق نتائج المكوّن: ما نوعها، ما دليلها، وما حدودها.",
    "unresolved": "عزل الأخطاء وإثبات التكامل لم يُستكملا. لا علاقة لهذا السرد بنتائج المشروع الفعلية.",
    "requirements": [
      "إكمال failure isolation ضمن نطاق هندسي محدد.",
      "توثيق synthetic checks وintegration limitations.",
      "مراجعة مستقلة للعقد قبل اعتباره مكتملًا."
    ],
    "limitations": "كل المتطلبات خيالية؛ لا data loading أو training أو financial evaluation."
  },
  "latest": {
    "title": "Mock Evidence Envelope Change",
    "changed": "في القصة الخيالية، أضفنا فصلًا بين النتيجة الهندسية ودليلها وحدودها، بدل عرض كلمة نجاح وحدها.",
    "why": "هذا يساعد مطوّر البوت يعرف ما الذي اختُبر فعلًا وما الذي بقي مجهولًا، قبل بناء مكوّن يعتمد عليه.",
    "verification": "MOCK ONLY: وصف فحوص عقد مصطنعة. هذه ليست نتائج اختبارات نُفّذت أو receipt حقيقية.",
    "limitations": "لا real-data replay، ولا نموذج fitted، ولا financial outcome. تفاصيل التحديث ليست سجلًا من Codex.",
    "impacts": [
      {
        "category": "Engineering",
        "description": "مثال: حدود المكوّن تصبح أوضح؛ لا اعتماد للنظام كاملًا."
      },
      {
        "category": "AI/ML",
        "description": "لا training أو predictions؛ الواجهة لا تثبت دقة النموذج."
      },
      {
        "category": "Strategy",
        "description": "لا تغيير للقواعد أو إشارات قرار."
      },
      {
        "category": "Financial Performance",
        "description": "لا نتائج مالية أو دليل ربحية."
      },
      {
        "category": "Risk",
        "description": "لا clearance؛ المخاطر لا تُحل باختبار UI."
      }
    ],
    "technical": [
      "MOCK path: fictional-bot/replay/envelope.py",
      "MOCK receipt: synthetic-contract-example",
      "Scope: isolated interface, no runtime integration"
    ]
  },
  "decision": {
    "title": "Review the Mock Replay Contract",
    "status": "approval",
    "description": "اقتراح واحد في السيناريو: مراجعة حدود عقد replay وما يحتاجه من دليل قبل أي تحسين هندسي لاحق.",
    "boundary": "يحتاج موافقة منفصلة. لا تنفيذ أو بحث أو تشغيل أو منح موافقة من هذا التصميم."
  }
};
  function freeze(value) {
    Object.values(value).forEach(item => { if (item && typeof item === "object") freeze(item); });
    return Object.freeze(value);
  }
  window.PROJECT_CONTROL_MOCK = freeze(fixture);
})();
