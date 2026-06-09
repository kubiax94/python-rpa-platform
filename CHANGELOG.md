# Changelog

## [0.10.0](https://github.com/kubiax94/python-rpa-platform/compare/v0.9.0...v0.10.0) (2026-06-09)


### Features

* **docker:** switch Guacamole data storage to named volumes for better persistence ([cf34aa4](https://github.com/kubiax94/python-rpa-platform/commit/cf34aa4c0e1f03b690ba89aacc83f615309303ab))


### Bug Fixes

* **agent-runtime:** prioritize reported process_count in session summary ([76675ee](https://github.com/kubiax94/python-rpa-platform/commit/76675ee2c19223617ad8546f040156ae217892e3))
* **agent:** prioritize process_count in getSessionProcessCount if available ([86a25a2](https://github.com/kubiax94/python-rpa-platform/commit/86a25a297154a52e4c04a53288a1764300c985f9))
* **command-panel:** ensure processCount uses process_count if available ([11b033f](https://github.com/kubiax94/python-rpa-platform/commit/11b033fe6a4e6475c68aaf6323978bba776efeb4))
* **overview-panel:** update procCount to prioritize process_count if available ([24decfb](https://github.com/kubiax94/python-rpa-platform/commit/24decfb24057ee06a21784e9457b4f7968eeadab))
* **process-manager:** track last reported PIDs to handle process status updates ([6973bb4](https://github.com/kubiax94/python-rpa-platform/commit/6973bb4e8df8a34775aaeec6242a41826828d72e))

## [0.9.0](https://github.com/kubiax94/python-rpa-platform/compare/v0.8.0...v0.9.0) (2026-06-08)


### Features

* **agent-access:** add AgentAccessPolicyPanel component for managing access policies ([f946db5](https://github.com/kubiax94/python-rpa-platform/commit/f946db5a9cf9046500946429ea0a3d0f06128e44))
* **agent-access:** add request models for agent permission rules and guacamole access updates ([1b4e94c](https://github.com/kubiax94/python-rpa-platform/commit/1b4e94c91fc799097175a474d5112daab0fa26b5))
* **agent-access:** remove AgentAccessDialog component ([c572b93](https://github.com/kubiax94/python-rpa-platform/commit/c572b9362e4d2d2fb0074b22afc72f1fec40e116))
* **agent-card:** update button label from 'Edit' to 'Policy' ([51296d9](https://github.com/kubiax94/python-rpa-platform/commit/51296d96230cb4ff268da3438b0291f0a008c87e))
* **agent-detail:** enhance access management with AgentAccessPolicyPanel and update tab sanitization logic ([995f612](https://github.com/kubiax94/python-rpa-platform/commit/995f612d441441741e8c8ada382302f531d57fb4))
* **agent-list:** update onSelectAgent to accept preferredTab and remove AgentAccessDialog ([0329052](https://github.com/kubiax94/python-rpa-platform/commit/03290527d2a8dd95a4f8c2a2492a94b4e524af73))
* **agent-tabs:** add AgentTab type definition for tab management ([caffb46](https://github.com/kubiax94/python-rpa-platform/commit/caffb46fcebd535e6b74404d88a9e3777cdb4185))
* **dashboard:** enhance agent selection with preferred tab state management ([cecb026](https://github.com/kubiax94/python-rpa-platform/commit/cecb02647bcd7da456fcc8f4cac204bb4ba08874))
* **guacamole-panel:** enhance access control with detailed permission checks and update UI logic ([c91f013](https://github.com/kubiax94/python-rpa-platform/commit/c91f0134dd6879a34b755ba96977ecaff0ba6f04))
* **guacamole-viewport:** enhance access control with effective permissions for file transfer and clipboard actions ([eb939a6](https://github.com/kubiax94/python-rpa-platform/commit/eb939a6a95782774debb04c53b2498ae8c589b03))
* **guacamoleAccess:** add initial access policy and permission management functions ([23a9001](https://github.com/kubiax94/python-rpa-platform/commit/23a90011d64efc56b996ce0b41ba182490f08ea4))
* **guacamole:** enhance access control with effective permissions for agent sessions ([13f19cb](https://github.com/kubiax94/python-rpa-platform/commit/13f19cb6a263ce0715cba752d3f1aaa8ec3d5ba9))
* **guacamole:** enhance permission management with normalization and effective permissions ([497b971](https://github.com/kubiax94/python-rpa-platform/commit/497b971f9420c7e8be7cd67bcc54ee428d1b916e))
* **guacamole:** update file transfer handling to use new permissions structure ([ab4a8a7](https://github.com/kubiax94/python-rpa-platform/commit/ab4a8a782a4f0fec321fbe2e2355dcc56f9b1ad3))
* **useGuacamole:** redefine access policy structure with granular permissions and rules ([001ea9b](https://github.com/kubiax94/python-rpa-platform/commit/001ea9b6d3586034515ec7df86d016a3b94e1a70))

## [0.8.0](https://github.com/kubiax94/python-rpa-platform/compare/v0.7.0...v0.8.0) (2026-06-08)


### Features

* **frontend:** added RBAC for gucamole bridge ([3188c7d](https://github.com/kubiax94/python-rpa-platform/commit/3188c7dc8d4b4a2899079ae46c2d828013a087f1))
* **server:** added RBAC for gucamole bridge ([085bb5b](https://github.com/kubiax94/python-rpa-platform/commit/085bb5bb227239ead21783e52d6fc0efb22b02b9))

## [0.7.0](https://github.com/kubiax94/python-rpa-platform/compare/v0.6.0...v0.7.0) (2026-06-08)


### Features

* **frontend:** added file trfansfer ([96e7e43](https://github.com/kubiax94/python-rpa-platform/commit/96e7e434ff32a2e510cb78aa97ce378e15027c3a))

## [0.6.0](https://github.com/kubiax94/python-rpa-platform/compare/v0.5.0...v0.6.0) (2026-06-08)


### Features

* **frontend:** agend edit and delete option ([24e0c61](https://github.com/kubiax94/python-rpa-platform/commit/24e0c61aa9d9527779404c03b2415503b573a707))
* **frontend:** agent  extended connection status ([4ddb63f](https://github.com/kubiax94/python-rpa-platform/commit/4ddb63f3b9952c03bb7ae322deda490d5298c0ee))
* **server:** agent removal added and edit ([f337833](https://github.com/kubiax94/python-rpa-platform/commit/f33783399e8642adceb0f4a5b9c4d8b3bc707651))

## [0.5.0](https://github.com/kubiax94/python-rpa-platform/compare/v0.4.3...v0.5.0) (2026-06-08)


### Features

* **frontend:** added guacamole clipboard ([b09371c](https://github.com/kubiax94/python-rpa-platform/commit/b09371cc6bdcb19969f419e1819b1080eb32a1db))


### Bug Fixes

* **server:** server is no longer providing new process to server ([1d4b014](https://github.com/kubiax94/python-rpa-platform/commit/1d4b014a8ce79c8462df1b19be63990d511c6845))

## [0.4.3](https://github.com/kubiax94/python-rpa-platform/compare/v0.4.2...v0.4.3) (2026-06-06)


### Bug Fixes

* **agent:** added FQDN to transport layer ([eae27c4](https://github.com/kubiax94/python-rpa-platform/commit/eae27c4d44b737c0c67f37b663c2410382ee578f))
* **agent:** added FQDN to transport layer ([1514ad8](https://github.com/kubiax94/python-rpa-platform/commit/1514ad89e9c73ed6a17df82e05682e68b37c5aac))
* **server:** added FQDN to transport layer ([a9d6f65](https://github.com/kubiax94/python-rpa-platform/commit/a9d6f650a2a942ef9916c7f5320c70cf13f5c63c))

## [0.4.2](https://github.com/kubiax94/python-rpa-platform/compare/v0.4.1...v0.4.2) (2026-06-06)


### Bug Fixes

* **agent:** added FQDN and hostname normalization ([7fe1949](https://github.com/kubiax94/python-rpa-platform/commit/7fe1949eb9cf68be2b3df52e30d4e2c4ce419de1))
* **server:** added FQDN and hostname normalization ([603e944](https://github.com/kubiax94/python-rpa-platform/commit/603e944278be2212570d33c5f50c53a8a455785c))

## [0.4.1](https://github.com/kubiax94/python-rpa-platform/compare/v0.4.0...v0.4.1) (2026-06-06)


### Bug Fixes

* **agent:** service installation fix ([f841326](https://github.com/kubiax94/python-rpa-platform/commit/f84132633ab94dce4afed5d2fb8d4dc9a029f397))

## [0.4.0](https://github.com/kubiax94/python-rpa-platform/compare/v0.3.0...v0.4.0) (2026-06-06)


### Features

* **infra:** added pat for releases ([ba9b294](https://github.com/kubiax94/python-rpa-platform/commit/ba9b294381c31d1107f3eb5d53000f4a822c58a3))

## [0.3.0](https://github.com/kubiax94/python-rpa-platform/compare/v0.2.0...v0.3.0) (2026-06-06)


### Features

* **infra:** added relese for exe ([47b7aef](https://github.com/kubiax94/python-rpa-platform/commit/47b7aef96d5635b065967def7a00d19f430e53c2))

## [0.2.0](https://github.com/kubiax94/python-rpa-platform/compare/v0.1.3...v0.2.0) (2026-06-06)


### Features

* **infra:** improve relese automation ([9f56010](https://github.com/kubiax94/python-rpa-platform/commit/9f56010b0a003c2720748f7a7a845cfa57959238))
* **script:** added script for release changes ([efb5337](https://github.com/kubiax94/python-rpa-platform/commit/efb53376c7673140640c87a96ef5ae285cb44d4c))


### Bug Fixes

* **frontend:** login screen, deploy ([f022bd1](https://github.com/kubiax94/python-rpa-platform/commit/f022bd128c44cf740644e5d5bd19fbd80af32955))

## [0.1.3](https://github.com/kubiax94/python-rpa-platform/compare/v0.1.2...v0.1.3) (2026-06-06)


### Bug Fixes

* frontend layout, login, deploy ([f19037d](https://github.com/kubiax94/python-rpa-platform/commit/f19037d65d987b4eb4b499e774642a258df975ca))

## [0.1.2](https://github.com/kubiax94/python-rpa-platform/compare/v0.1.1...v0.1.2) (2026-06-06)


### Bug Fixes

* switch deploy to github release ([ad15a90](https://github.com/kubiax94/python-rpa-platform/commit/ad15a90cf77b1766467c4c6a6bb693fc3832bec3))
* switch deploy to github release ([a159819](https://github.com/kubiax94/python-rpa-platform/commit/a159819cf92926eaf59e2709a3450e2fef3bdbba))

## [0.1.1](https://github.com/kubiax94/python-rpa-platform/compare/v0.1.0...v0.1.1) (2026-06-06)


### Bug Fixes

* test relese flow ([a77d0bc](https://github.com/kubiax94/python-rpa-platform/commit/a77d0bc5927adedd356f412bfc7aabf40ef539dc))
