import { Link } from "react-router-dom";

import { useLanguage } from "../i18n";
import { markIntroSeen } from "./introSeen";

export function BrandHomeLink() {
  const { t } = useLanguage();

  // Every activation acknowledges the intro gate before routing to `/`.
  // Context-menu handling also preserves homepage behavior for “open in new tab”.
  return (
    <Link
      className="v2-wordmark"
      to="/"
      onClick={markIntroSeen}
      onAuxClick={(event) => {
        if (event.button === 1) markIntroSeen();
      }}
      onContextMenu={markIntroSeen}
    >
      {t("枝涯")}
    </Link>
  );
}
