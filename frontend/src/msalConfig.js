
import { PublicClientApplication } from "@azure/msal-browser";

export const msalInstance = new PublicClientApplication({
  auth: {
    clientId: "a9bda2e7-4cd0-4203-9ae0-62635c58d984",
    authority: "https://login.microsoftonline.com/9f58333b-9cca-4bd9-a7d8-e151e43b79f3",
    redirectUri: "https://kpmg-internship-project-seven.vercel.app/",
  },
  cache: { cacheLocation: "sessionStorage" },
});
