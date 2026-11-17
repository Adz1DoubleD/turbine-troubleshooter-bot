# Changelog

## [2.0.2](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/compare/v2.0.1...v2.0.2) (2026-11-17)


### Bug Fixes

* show pending access and admin requests in a host bot ([cea6050](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/cea605085bfee817d1a04747cba2fad329f12a1b))
* show pending access and admin requests in a host bot ([486ef91](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/486ef9119be1e1453826e8346c527aebcb38853f))
* tell users about decisions made from a host bot ([3715dce](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/3715dce11be3c0efb4ece4930af4b2a21dbd35c9))
* tell users about decisions made from a host bot ([890196c](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/890196c7e708b70f95255f8eb206d849f7471594))

## [2.0.1](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/compare/v2.0.0...v2.0.1) (2026-11-17)


### Bug Fixes

* hide Suggest Content when the menu is shown inside a host bot ([4028bb2](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/4028bb2c24a819e0a98599e68895295b9c87a664))
* hide Suggest Content when the menu is shown inside a host bot ([efa8055](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/efa8055dbcb5bd5499a3cc3d671e18b44f5a84cc))
* make the Request Admin button work ([3d627d6](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/3d627d6f9a0ef28e83dd789107e8b9a1085770d2))
* make the Request Admin button work ([3e3abfa](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/3e3abfaa580d62418764197b8832fb7eb6624d57))

## [2.0.0](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/compare/v1.1.3...v2.0.0) (2026-11-17)


### ⚠ BREAKING CHANGES

* hosts that relied on local runs being detected automatically must pass test_mode=True (or set TROUBLESHOOTER_TEST_MODE=1) when testing, or notifications reach real users.

### Bug Fixes

* let the host choose test mode instead of guessing from Heroku ([1d13c8b](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/1d13c8b46a135ca275f379ff2a34aaf567162b8e))

## [1.1.3](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/compare/v1.1.2...v1.1.3) (2026-11-16)


### Bug Fixes

* enhance callback handling and user interaction ([855acae](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/855acae120e35449a3a452185ff41bdd34349a0c))

## [1.1.2](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/compare/v1.1.1...v1.1.2) (2026-11-16)


### Bug Fixes

* remove PART_ACCESSORIES from content structure and update related tests ([a306096](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/a3060964caffc93950dc544627440fb0a78962cb))

## [1.1.1](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/compare/v1.1.0...v1.1.1) (2026-11-16)


### Bug Fixes

* publish callback navigation update ([78ae291](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/78ae2914757d96417a140c12bc60e2a34c6d596f))

## [1.1.0](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/compare/v1.1.0...v1.1.0) (2026-11-16)


### ⚠ BREAKING CHANGES

* hosts that relied on JAWSDB_URL must set TROUBLESHOOTER_DB_URL.

### Features

* require TROUBLESHOOTER_DB_URL instead of falling back to JAWSDB_URL ([4f3fbd1](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/4f3fbd1e75279868911631ca624c546b73022b8c))


### Dependencies

* **deps-dev:** bump the python group across 1 directory with 2 updates ([63b27f2](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/63b27f22416718aa7a3246b5ad923309af0d267e))


### Documentation

* explain creating the bot, owner ID and alerts chat ([45ba533](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/45ba5338e623a3007658d68555c8c6c4fbab375d))


### Miscellaneous Chores

* set release version ([646ac8d](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/646ac8d1f41609f600f03e2b28e1edcc822f80b7))

## [1.1.0](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/compare/turbine-troubleshooter-bot-v1.0.0...turbine-troubleshooter-bot-v1.1.0) (2026-11-16)


### ⚠ BREAKING CHANGES

* hosts that relied on JAWSDB_URL must set TROUBLESHOOTER_DB_URL.

### Features

* require TROUBLESHOOTER_DB_URL instead of falling back to JAWSDB_URL ([4f3fbd1](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/4f3fbd1e75279868911631ca624c546b73022b8c))


### Dependencies

* **deps-dev:** bump the python group across 1 directory with 2 updates ([63b27f2](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/63b27f22416718aa7a3246b5ad923309af0d267e))


### Documentation

* explain creating the bot, owner ID and alerts chat ([45ba533](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/45ba5338e623a3007658d68555c8c6c4fbab375d))


### Miscellaneous Chores

* set release version ([646ac8d](https://github.com/Adz1DoubleD/turbine-troubleshooter-bot/commit/646ac8d1f41609f600f03e2b28e1edcc822f80b7))
