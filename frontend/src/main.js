import { createApp } from "vue";
import App from "./App.vue";
import "./styles.css";

const app = createApp(App);
app.mount("#app");

// API workflows bind to DOM targets rendered by the Vue component tree.
await import("./controllers/appController.js");
