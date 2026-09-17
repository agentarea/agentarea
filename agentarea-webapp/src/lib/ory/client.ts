// Copyright © 2024 Ory Corp
// SPDX-License-Identifier: Apache-2.0
//
// Derived from @ory/nextjs (Apache-2.0).

import { Configuration, FrontendApi } from "@ory/client-fetch";
import { orySdkUrl } from "./url";

export const serverSideFrontendClient = () =>
  new FrontendApi(
    new Configuration({
      headers: {
        Accept: "application/json",
      },
      basePath: orySdkUrl(),
    })
  );
