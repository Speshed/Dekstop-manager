# Project instructions

Use RTK (Rust Token Killer) as a transparent command prefix whenever it is
available in the environment:

```text
rtk <command>
```

For command chains, prefix each command segment with `rtk`. If `rtk` is not
installed or unavailable on `PATH`, run the underlying command directly and
report that RTK is unavailable.
