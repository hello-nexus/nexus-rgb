# Contributing

## License

This repository is licensed under AGPL-3.0 (see [`LICENSE`](LICENSE)). By
contributing, you agree your contributions are licensed under AGPL-3.0 and the
terms in [`CLA.md`](CLA.md).

## Tested on the device, or not merged

This workspace builds and bundles the headless OpenRGB fork that nexus-service
drives. Device code lives in the fork
([`hello-nexus/openrgb-headless`](https://github.com/hello-nexus/openrgb-headless));
this repo holds the build and bundle scripts and the merge notes.

Every pull request that changes a script, the bundle, or the fork pointer must
have been built and run by the contributor, on the contributor's own machine,
with nexus-service driving the resulting binary against a physical RGB device.
There is no lab that does this for you. A pull request without that is closed,
whatever its size.

1. Build the fork with the change and bundle it the way the scripts do.
2. Run nexus-service against that bundle with the device attached and confirm
   the device is detected and driven.
3. Fill in the Validation section of the pull request template. Write down
   what you observed, not what you expect.

If you cannot test a change on the hardware, do not send it. Open an issue and
describe what you found.

## If an AI agent writes the change

The same rules apply, and the person who opens the pull request answers for
them. An agent cannot run the result on your machine, so the validation
section describes what you ran, on your machine, in your words. A pull request
whose validation text does not match what was run is closed.

## Standards

- One topic per pull request.
- Device-code changes go to the fork, not here. Keep the fork mergeable with
  upstream OpenRGB; `README.md` explains what that means in practice.
- Match the surrounding scripts. Do not reformat, rename or reorganize anything
  the change does not need.
- Keep `README.md` true. If the change alters how the fork is built, bundled
  or laid out, update the README in the same pull request.
- Read every line you submit, generated or not, and be able to say why it is
  there.

## Workflow

1. Fork and branch from `main`.
2. Open the pull request against `main` and complete every section of the
   template.
3. Confirm in the pull request that you have read and agree to
   [`CLA.md`](CLA.md).
4. Answer review with new commits. After any change, test again and update
   the validation section.
