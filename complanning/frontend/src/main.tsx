import { StrictMode, type ReactElement } from "react";
import { createRoot } from "react-dom/client";
import { LuCompass, LuShieldCheck } from "react-icons/lu";
import "./styles.css";
import { Shell } from "./components/Shell";
import { Button, Empty, ToastProvider } from "./components/ui";
import { I18nProvider, useI18n } from "./lib/i18n";
import { match, navigate, usePath } from "./lib/router";
import { SessionProvider, useSession } from "./lib/session";
import { ThemeProvider } from "./lib/theme";
import { Audit } from "./pages/Audit";
import { ChangePasswordPage, ForcedPasswordChange } from "./pages/ChangePassword";
import { Companies } from "./pages/Companies";
import { Home } from "./pages/Home";
import { Login } from "./pages/Login";
import { Settings } from "./pages/Settings";
import { Sites } from "./pages/Sites";
import { Users } from "./pages/Users";
import { Logo } from "./components/Logo";
import { BomEditor, Boms } from "./pages/master/Boms";
import { CalendarPage } from "./pages/master/Calendar";
import { Items } from "./pages/master/Items";
import { Machines } from "./pages/master/Machines";
import { RoutingEditor, Routings } from "./pages/master/Routings";
import { Units } from "./pages/master/Units";
import { Campaigns } from "./pages/rules/Campaigns";
import { Changeovers } from "./pages/rules/Changeovers";
import { ItemTimesPage } from "./pages/rules/ItemTimes";

function NotFound() {
  const { t } = useI18n();
  return <div className="panel"><Empty icon={<LuCompass />} title={t("notFound.title")} body={t("notFound.body")}
    action={<Button onClick={() => navigate("/")}>{t("notFound.home")}</Button>} /></div>;
}

function Forbidden() {
  const { t } = useI18n();
  return <div className="panel"><Empty icon={<LuShieldCheck />} title={t("forbidden.title")} body={t("forbidden.body")}
    action={<Button onClick={() => navigate("/")}>{t("notFound.home")}</Button>} /></div>;
}

function Routes() {
  const path = usePath();
  const { me } = useSession();
  if (!me) return null;
  const platform = me.user.is_platform_admin;
  const admin = me.user.is_tenant_admin;
  const gate = (ok: boolean, el: ReactElement) => (ok ? el : <Forbidden />);
  const tenantUser = !!me.tenant;
  let m: Record<string, string> | null;
  if ((m = match("/master/boms/:id", path))) return gate(tenantUser, <BomEditor key={m.id} itemId={m.id} />);
  if ((m = match("/master/routings/:id", path))) return gate(tenantUser, <RoutingEditor key={m.id} itemId={m.id} />);
  switch (path) {
    case "/master/items": return gate(tenantUser, <Items />);
    case "/master/units": return gate(tenantUser, <Units />);
    case "/master/boms": return gate(tenantUser, <Boms />);
    case "/master/machines": return gate(tenantUser, <Machines />);
    case "/master/routings": return gate(tenantUser, <Routings />);
    case "/master/calendar": return gate(tenantUser, <CalendarPage />);
    case "/rules/changeovers": return gate(tenantUser, <Changeovers />);
    case "/rules/campaigns": return gate(tenantUser, <Campaigns />);
    case "/rules/times": return gate(tenantUser, <ItemTimesPage />);
    case "/": return <Home />;
    case "/companies": return gate(platform, <Companies />);
    case "/users": return gate(admin, <Users />);
    case "/sites": return gate(admin, <Sites />);
    case "/settings": return gate(admin, <Settings />);
    case "/audit": return gate(platform || admin, <Audit />);
    case "/account/password": return <ChangePasswordPage />;
    default: return <NotFound />;
  }
}

function App() {
  const { status, me } = useSession();
  if (status === "loading") return <div className="boot" aria-busy="true"><Logo height={40} /></div>;
  if (status === "signed-out" || !me) return <Login />;
  if (me.user.must_change_password) return <ForcedPasswordChange />;
  return <Shell><Routes /></Shell>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <I18nProvider>
        <ToastProvider>
          <SessionProvider>
            <App />
          </SessionProvider>
        </ToastProvider>
      </I18nProvider>
    </ThemeProvider>
  </StrictMode>,
);
