'use strict';

class DisabledAdmZip {
  constructor() {
    throw new Error('ZIP decompression is disabled in the CS2 Game Coordinator bridge');
  }
}

module.exports = DisabledAdmZip;
