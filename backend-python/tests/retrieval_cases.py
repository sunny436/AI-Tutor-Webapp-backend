"""
Shared retrieval evaluation set.

One place for "this query should find this note", used by both the embedding
bake-off (`scripts/eval_embeddings.py`) and the retrieval test suite
(`tests/test_retrieval.py`), so the model we pick and the behaviour we ship are
measured against exactly the same bar.

Three scripts on purpose. Users of this app type all three, often in one
sentence, and they fail differently:

  DEVANAGARI  what a Hindi keyboard produces. Multilingual embedders handle it
              well — it is in their training data.
  HINGLISH    Hindi in Latin letters. The hard case, and the most common one.
              Largely out-of-distribution for every embedder, which is why
              retrieval also carries an alias index (`knowledge.match_topics`).
  ENGLISH     the easy baseline.

NEGATIVES matter as much as positives. A retriever that returns the least-bad
note for "who won the world cup" is worse than one that returns nothing: the
prompt labels whatever comes back as trusted knowledge, and the model will build
an answer around it.
"""

# (query, expected source file)
DEVANAGARI: list[tuple[str, str]] = [
    ("पेट में जलन और खट्टी डकार", "acidity.md"),
    ("गैस और पेट फूलना", "gas-bloating.md"),
    ("कब्ज का इलाज", "constipation.md"),
    ("बवासीर की समस्या", "piles.md"),
    ("सिर दर्द और माइग्रेन", "migraine-headache.md"),
    ("नींद नहीं आती", "insomnia.md"),
    ("तनाव और चिंता", "stress-anxiety.md"),
    ("बाल झड़ रहे हैं", "hair-fall.md"),
    ("चेहरे पर मुहांसे", "acne.md"),
    ("जोड़ों का दर्द", "joint-pain.md"),
    ("कमर दर्द", "back-pain.md"),
    ("थायराइड के लक्षण", "thyroid.md"),
    ("शुगर कैसे कंट्रोल करें", "diabetes.md"),
    ("वजन कैसे कम करें", "weight-loss.md"),
    ("पीरियड समय पर नहीं आते", "irregular-periods.md"),
    ("अश्वगंधा के फायदे", "common-herbs.md"),
    ("रोग प्रतिरोधक शक्ति कैसे बढ़ाएं", "immunity.md"),
    ("रूसी की समस्या", "dandruff.md"),
]

HINGLISH: list[tuple[str, str]] = [
    ("pet mein jalan aur khatti dakar", "acidity.md"),
    ("mujhe acidity hai", "acidity.md"),
    ("pet phoolna", "gas-bloating.md"),
    ("gas ki problem", "gas-bloating.md"),
    ("kabz ka ilaj", "constipation.md"),
    ("pet saaf nahi hota", "constipation.md"),
    ("loose motion ho rahe hain", "loose-motions.md"),
    ("bawaseer ka ilaj", "piles.md"),
    ("khana hazam nahi hota", "indigestion.md"),
    ("sar dard", "migraine-headache.md"),
    ("neend nahi aati", "insomnia.md"),
    ("ghabrahat aur tension", "stress-anxiety.md"),
    ("mann nahi lagta udas rehta hoon", "low-mood.md"),
    ("baal jhad rahe hain", "hair-fall.md"),
    ("sar mein rusi", "dandruff.md"),
    ("chehre par daane", "acne.md"),
    ("skin dull ho gayi hai", "dry-skin-glow.md"),
    ("ghutne mein dard", "joint-pain.md"),
    ("kamar dard", "back-pain.md"),
    ("hamesha thakan rehti hai", "fatigue-weakness.md"),
    ("immunity kaise badhaye", "immunity.md"),
    ("thyroid ke liye kya khana chahiye", "thyroid.md"),
    ("shugar control kaise kare", "diabetes.md"),
    ("cholesterol kam karna hai", "cholesterol.md"),
    ("bp high rehta hai", "blood-pressure.md"),
    ("motapa kam karna hai", "weight-loss.md"),
    ("wajan badhana hai dubla hoon", "weight-gain.md"),
    ("pcos ki problem", "pcos.md"),
    ("periods time par nahi aate", "irregular-periods.md"),
    ("period ke time bahut dard hota hai", "period-pain.md"),
    ("menopause ke lakshan", "menopause.md"),
    ("ashwagandha ke fayde", "common-herbs.md"),
    ("triphala kis kaam aata hai", "common-herbs.md"),
]

ENGLISH: list[tuple[str, str]] = [
    ("acidity and heartburn remedies", "acidity.md"),
    ("bloating and gas relief", "gas-bloating.md"),
    ("constipation treatment", "constipation.md"),
    ("haemorrhoids ayurveda", "piles.md"),
    ("migraine headache", "migraine-headache.md"),
    ("insomnia and poor sleep", "insomnia.md"),
    ("anxiety and stress management", "stress-anxiety.md"),
    ("hair fall treatment", "hair-fall.md"),
    ("acne and pimples", "acne.md"),
    ("dry skin and glow", "dry-skin-glow.md"),
    ("knee joint pain arthritis", "joint-pain.md"),
    ("lower back pain", "back-pain.md"),
    ("chronic fatigue and weakness", "fatigue-weakness.md"),
    ("how to boost immunity", "immunity.md"),
    ("thyroid diet", "thyroid.md"),
    ("diabetes blood sugar control", "diabetes.md"),
    ("high cholesterol", "cholesterol.md"),
    ("high blood pressure", "blood-pressure.md"),
    ("weight loss plan", "weight-loss.md"),
    ("pcos polycystic ovary", "pcos.md"),
    ("painful periods", "period-pain.md"),
    ("menopause symptoms", "menopause.md"),
    ("ashwagandha benefits", "common-herbs.md"),
]

# Must retrieve NOTHING. Anything returned here gets labelled "trusted
# knowledge" in the prompt and the model will build an answer around it.
NEGATIVES: list[str] = [
    "who won the world cup",
    "capital of france",
    "best phone under 20000",
    "how to fix a python bug",
    "tell me a joke",
    "aaj mausam kaisa hai",
    "2+2 kitna hota hai",
    "bitcoin ka rate kya hai",
    "movie recommend karo",
    "write me a poem about the sea",
]

POSITIVES = DEVANAGARI + HINGLISH + ENGLISH
ALL_SOURCES = sorted({source for _, source in POSITIVES})
