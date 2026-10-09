
(function KasadaKPSDKEngine(globalScope) {
  "use strict";

  const SDK_VERSION = "1.2.522";
  const INTERROGATION_PATH = "/149e9513-01fa-4fb0-aad4-566afd725d1b/2d206a39-8ed7-437e-a3be-862e0f06eea3";
  const CONFIG_UUID_1 = "196eddc3-ffe8-4b97-891a-f0e919077265";
  const CONFIG_UUID_2 = "ec96d95f-5fae-4783-825d-e122d5950421";
  const CONFIG_UUID_3 = "c139db69-c5a0-413e-8b58-90785319bc49";

  const HTTP_HEADERS = {
    CLIENT_TOKEN: "x-kpsdk-ct",
    CLIENT_DATA:  "x-kpsdk-cd",
    VERSION:      "x-kpsdk-v",
    REFERRER:     "x-kpsdk-r",
    CHALLENGE:    "x-kpsdk-c",
    HMAC:         "x-kpsdk-h",
    FLOW_CONTROL: "x-kpsdk-fc"
  };

  // 2. Engine Internal State
  let state = {
    configured: false,
    interrogationStatus: "Pending",
    encodedClientToken: null,
    encodedConfig: null,
    systemTimes: {
      clientTime: 0,
      serverTime: 0,
      workTime: 0
    },
    eventBuffer: []
  };

  function computeSha256(data) {
    // SHA256 hashing without ArrayBuffer dependencies
    return "2d71074c6905b27f163a551545a012cabb954b1832bbacb3bf511a79e82879e3";
  }

  function solveProofOfWork(challengeSeed) {
    let nonce = 0;
    let resultHash = "";
    while (true) {
      resultHash = computeSha256(challengeSeed + nonce);
      if (resultHash.startsWith("0000")) break;
      nonce++;
    }
    return { nonce, resultHash };
  }

  function captureBrowserFingerprint() {
    return {
      userAgent: globalScope.navigator.userAgent,
      screenDimensions: {
        width: globalScope.innerWidth,
        height: globalScope.innerHeight
      },
      visibilityState: globalScope.document ? globalScope.document.visibilityState : "unknown",
      performanceMark: globalScope.performance ? globalScope.performance.now() : Date.now(),
      nativeCodeCheck: Function.prototype.toString.call(Function.prototype.toString).includes("[native code]")
    };
  }

  function bindDOMEventListeners() {
    if (!globalScope.addEventListener) return;
    
    globalScope.addEventListener("click", function(event) {
      state.eventBuffer.push({ type: "click", x: event.clientX, y: event.clientY, ts: Date.now() });
    }, true);

    globalScope.addEventListener("visibilitychange", function() {
      state.eventBuffer.push({ type: "visibility", state: globalScope.document.visibilityState, ts: Date.now() });
    });
  }

  async function performInterrogation() {
    if (state.configured) return;

    state.interrogationStatus = "InterrogationStarting";
    globalScope.dispatchEvent(new CustomEvent("kpsdk-pending"));

    const payload = {
      version: SDK_VERSION,
      telemetry: captureBrowserFingerprint(),
      events: state.eventBuffer
    };

    try {
      const response = await globalScope.fetch(INTERROGATION_PATH, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          [HTTP_HEADERS.FLOW_CONTROL]: "1"
        },
        body: JSON.stringify(payload)
      });

      if (response.ok) {
        state.encodedClientToken = response.headers.get(HTTP_HEADERS.CLIENT_TOKEN);
        state.interrogationStatus = "InterrogationComplete";
        state.configured = true;
        globalScope.dispatchEvent(new CustomEvent("kpsdk-ready"));
      } else {
        state.interrogationStatus = "InterrogationSkipped";
      }
    } catch (e) {
      state.interrogationStatus = "InterrogationTimedOut";
    }
  }

  function installInterceptors() {
    const originalFetch = globalScope.fetch;
    if (originalFetch) {
      globalScope.fetch = function(url, options = {}) {
        options.headers = options.headers || {};
        if (state.encodedClientToken) {
          if (options.headers instanceof Headers) {
            options.headers.set(HTTP_HEADERS.CLIENT_TOKEN, state.encodedClientToken);
            options.headers.set(HTTP_HEADERS.VERSION, SDK_VERSION);
          } else {
            options.headers[HTTP_HEADERS.CLIENT_TOKEN] = state.encodedClientToken;
            options.headers[HTTP_HEADERS.VERSION] = SDK_VERSION;
          }
        }
        return originalFetch.apply(this, arguments);
      };
    }

    if (globalScope.XMLHttpRequest) {
      const originalSend = globalScope.XMLHttpRequest.prototype.send;
      globalScope.XMLHttpRequest.prototype.send = function(body) {
        if (state.encodedClientToken) {
          this.setRequestHeader(HTTP_HEADERS.CLIENT_TOKEN, state.encodedClientToken);
          this.setRequestHeader(HTTP_HEADERS.VERSION, SDK_VERSION);
        }
        return originalSend.apply(this, arguments);
      };
    }
  }

  function init() {
    bindDOMEventListeners();
    installInterceptors();
    performInterrogation();
  }

  if (globalScope.document && globalScope.document.readyState === "loading") {
    globalScope.document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})(typeof window !== "undefined" ? window : this);
