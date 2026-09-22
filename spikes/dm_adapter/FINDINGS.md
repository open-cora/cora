# Findings

What the vendor client puts on the wire, and whether anything else has to.
Everything below is either printed by `compare.py` or read out of the
installed package, and the two are marked apart wherever it matters.

Run against aps-dm-api 10.1.0 (noarch, from the facility's own conda
channel), httpx 0.28.1, Python 3.13.12.

This is the first evidence against the questions in the README, and it
answers a fifth one that was not on the list and turned out to govern the
other four.

## The short version

**The adapter does not need the vendor package.** Driven against the same
recording stub, the vendor client and forty lines of httpx send byte for
byte the same requests: same method, same path, same body, same content
type, same cookie. This is the store spike's result reached a second time,
and it matters more here than it did there.

**It matters more because the vendor client does not authenticate the
server.** Its HTTPS connection sets `CERT_NONE` unconditionally, and the
line that would restore verification when a CA certificate is configured
is commented out. Anything that imports it talks to an unverified server
no matter how carefully the caller is written, because the defect is below
the caller's floor.

**Two quirks have to be reproduced rather than fixed.** A path segment is
base64-encoded twice and then leaks a Python `bytes` repr into the URL, so
the service is sent `b'...'`, quotes and all. And a GET carries
`Content-Type: html`, which is not a media type. Both are load-bearing on
the server side.

**Errors arrive in a header on an HTTP 200.** A client that checks the
status line sees success and a JSON body. The failure is in
`Dm-Status-Code`, and reproducing that check is not optional.

**What this does not settle** is anything about a real deployment. The
stub is a stub. Sections 1 to 4 are about what a faithful client must
send, which is exactly the part that decides the dependency question, and
nothing here says what a real server answers.

## 1. The two clients are indistinguishable at the socket

`compare.py` starts a recording server, drives it once with
`ExperimentDsApi.getExperimentByName` and once with httpx, and compares
what arrived.

```
   vendor client
     1. POST /dm/login
        content-type: application/x-www-form-urlencoded
        body:         'username=dmuser&password=dmpass'
     2. GET /dm/experimentsByName/b'ZEc5dGJ5MHlNREkyTFRFPQo='/2bm
        content-type: html
        cookie:       SESSIONID=...

   httpx reimplementation
     1. POST /dm/login                       (identical)
     2. GET /dm/experimentsByName/...        (identical)
```

The whole protocol is a form POST to `/dm/login`, a `Set-Cookie` back, and
that cookie on every later request. There is no signing, no token
exchange, no negotiation and no non-HTTP transport anywhere in the
package: a search for a message queue, a socket server or a stream client
across all 249 modules returns nothing.

Two of the three differences in the first run were mine rather than the
protocol's. The path is `/dm/experimentsByName/...`, not the
`/experiments/getByName/...` spelling that the archive endpoints use, and
the content type is the literal string below. Both were corrected by
reading what the vendor sent, which is the method working.

## 2. The path encoder, and the leak that is now part of the protocol

`Encoder.encode` base64-encodes twice. The second pass is deliberate and
the comment says why: one pass can produce a `+`, which is read as a space
after one decode.

What is not deliberate is the return type. It returns `bytes`, and every
call site interpolates it into an f-string, so what reaches the URL is the
Python repr:

```
   experiment name   tomo-2026-1
   on the wire       b'ZEc5dGJ5MHlNREkyTFRFPQo='
```

The `b`, both single quotes and the `=` padding are all in the path
segment. This is not a bug that happens to work by accident: the matching
`Encoder.decode` opens with `if encodedData.startswith("b'")` and strips
it back off, so both ends depend on it. A reimplementation that emits
clean base64 is talking to nothing.

`repr()` on the encoded bytes reproduces it exactly, which is what
`dm_encode` in `compare.py` does.

## 3. A GET that declares a content type, and the type is not one

Every session request defaults to `contentType='html'` and sets it as a
header, including on GETs that carry no body. `html` is not a media type.

Nothing observed here depends on it, and it costs one header to match, so
`compare.py` matches it rather than arguing. Whether the service cares is
a question for a real deployment.

## 4. The failure channel is a header, not the status line

The stub was set to answer 200, with a JSON body, and
`Dm-Status-Code: 14`:

```
   vendor client:   raised ObjectNotFound: Experiment tomo-2026-1 not found.
   httpx:           raised DmError: Dm-Status-Code 14: ... not found.
```

The status line said 200 in both cases. `DmExceptionMapper.checkStatus`
reads `Dm-Status-Code`, treats 0 as success, and maps 22 other integers
onto a typed exception hierarchy through `DM_EXCEPTION_MAP`. The codes
worth naming: 5 authorization, 6 authentication, 12 invalid session, 14
object not found, 15 already exists, 16 invalid object state, 19 service
limit, 22 task timeout.

That taxonomy is the best thing in the package and is worth keeping in an
adapter. It is also the one piece of the protocol a reimplementation is
most likely to omit, and omitting it turns every service error into a
successful read of a body that does not mean what it appears to.

## 5. What importing the vendor package would cost

Read out of the installed package rather than observed, except where
noted.

**Certificate verification is off.** `dmHttpsConnection.py`:

```python
context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
context.verify_mode = ssl.CERT_NONE
if caCertFile is not None:
    #context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(caCertFile)
```

Checked rather than assumed: after that exact sequence including the load,
`verify_mode` is 0 and `check_hostname` is False. Encrypted, unauthenticated.
It compounds, because `getUrl()` resolves the host with
`socket.gethostbyname` and puts the address in the URL, and the socket is
wrapped with no `server_hostname`, so no SNI is sent and hostname checking
could not work even if the commented line were restored.

**Session expiry is computed in the wrong timezone.** `loadSession` parses
a GMT cookie expiry with `strptime(..., '%Z')` and then `time.mktime`,
which reads the result as local time. Measured in Chicago: six hours of
skew, in the direction that treats an expired session as still valid.

**Content-Length is measured on the wrong object.** The header is set from
`len(data)`, the dict, rather than from the encoded body.

Also, for scale rather than as separate findings: 72 mutable `{}` default
arguments, 76 bare `except Exception`, Python 2/3 compatibility shims in 6
modules, 3 type annotations across 18,238 lines, hardcoded `AF_INET`, and
no tests in the distribution.

None of this is reachable through the wire, which is the point. Speak the
protocol and none of it is inherited.

## 6. What the package is good at, which is not nothing

The exception hierarchy in section 4. Full docstrings with parameters,
types, raised exceptions and doctest examples on public API methods. Named
constants rather than magic strings throughout. Five services behind one
consistent shape.

It reads as competent work that stopped being modernised, not as work done
carelessly. The defects in section 5 are in the transport, which is the
layer nobody revisits once it works.

## 7. Something the endpoint list gave away

The package exposes the beamline scheduling and safety-form databases
alongside data management: `/bss/beamlineProposals/...`, `/bss/runs/current`,
`/esaf/stationEsafs/...`, and `BssApsDbApi` and `EsafApsDbApi` beside the
storage and processing APIs.

So the proposal and safety-approval systems are reachable through the same
door, the same session cookie and the same client decision. Whatever this
adapter concludes about one applies to all three, and a gap analysis that
treated them as separate integrations was counting wrong.

There is also `/globusRuns/...` under the processing service, which is
where a transfer would be visible if one is ever modelled.

## 8. What is still open

Questions 1 through 4 in the README are untouched by any of this. They are
about what a real deployment stores, returns and takes how long to do it,
and no stub can answer them.

What changed is their cost. They can now be asked over plain httpx against
a real server by someone with an account, with no conda environment, no
vendor package and no unverified TLS, using `compare.py`'s client as the
starting point. That was the fifth question, and it was worth asking
first.
