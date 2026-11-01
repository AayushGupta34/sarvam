// Mirror of backend/app/config/languages.py. tests/test_backend.py checks they match.
export interface Language {
  name: string;
  code: string;
  native: string;
}

export const LANGUAGES: Language[] = [
  { name: "Assamese", code: "as-IN", native: "অসমীয়া" },
  { name: "Bengali", code: "bn-IN", native: "বাংলা" },
  { name: "Bodo", code: "brx-IN", native: "बड़ो" },
  { name: "Dogri", code: "doi-IN", native: "डोगरी" },
  { name: "Gujarati", code: "gu-IN", native: "ગુજરાતી" },
  { name: "Hindi", code: "hi-IN", native: "हिन्दी" },
  { name: "Kannada", code: "kn-IN", native: "ಕನ್ನಡ" },
  { name: "Kashmiri", code: "ks-IN", native: "कॉशुर / کٲشُر" },
  { name: "Konkani", code: "kok-IN", native: "कोंकणी" },
  { name: "Maithili", code: "mai-IN", native: "मैथिली" },
  { name: "Malayalam", code: "ml-IN", native: "മലയാളം" },
  { name: "Manipuri", code: "mni-IN", native: "মৈতৈলোন্" },
  { name: "Marathi", code: "mr-IN", native: "मराठी" },
  { name: "Nepali", code: "ne-IN", native: "नेपाली" },
  { name: "Odia", code: "od-IN", native: "ଓଡ଼ିଆ" },
  { name: "Punjabi", code: "pa-IN", native: "ਪੰਜਾਬੀ" },
  { name: "Sanskrit", code: "sa-IN", native: "संस्कृतम्" },
  { name: "Santali", code: "sat-IN", native: "ᱥᱟᱱᱛᱟᱲᱤ" },
  { name: "Sindhi", code: "sd-IN", native: "सिन्धी / سنڌي" },
  { name: "Tamil", code: "ta-IN", native: "தமிழ்" },
  { name: "Telugu", code: "te-IN", native: "తెలుగు" },
  { name: "Urdu", code: "ur-IN", native: "اردو" },
  { name: "English (India)", code: "en-IN", native: "English" },
];
