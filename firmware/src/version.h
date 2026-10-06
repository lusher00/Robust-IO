#ifndef VERSION_H
#define VERSION_H
/* Numeric version reported on CAN. FW_VERSION (git describe) is set by the Makefile. */
#define FW_VER_MAJOR  0
#define FW_VER_MINOR  3
#ifndef FW_VERSION
#define FW_VERSION    "unknown"
#endif
#endif
