# Offline full native source verification

Requires Python 3, a Java 21 runtime containing `jdk.compiler`, and the existing
external dependency packages named by `../reactive-r1_4/BUILD-CONFIG.json`.
Dependencies are not downloaded or included in this repository.

```sh
python3 client-mod/validation/current-native/verify.py \
  --dependency-root /path/to/external-pinned-packages \
  --reference-jar /path/to/final-r1.4.jar \
  --output /path/to/new-verification-output
```

`--output` must not exist. `--java` (or `JAVA`) may select the Java 21 executable.
The optional reference JAR must have SHA-256
`29141caad50641cdcfc9826a138ff30b2cfd7c555e24ce726fd03abbe366b68e`.
Without `--reference-jar`, the script compiles and counts classes but **does not
claim binary equivalence**; its receipt explicitly records `NOT_REQUESTED`.

The verifier checks all 120 dependency pins using sibling reactive-r1_4 metadata,
checks the unchanged original access-transformer rules, then compiles all 269
production Java sources. It applies those existing rules to real pinned Minecraft
class bytes in a temporary **compile-only** overlay; it adds no access rules and
never packages that overlay into the mod. The expected output is 632 classes.
With the reference supplied, every class name and byte is compared, including
missing or extra classes. Logs, source/class hashes, and receipts go only into
the requested output directory. The production source tree is not modified.

This is an offline mapped-source compile, **not** a full Gradle build, resource
packaging check, loader/mixin application test, or live gameplay test. It does
not install a JAR, launch Minecraft, alter a world, or use the network. The
external pinned classpath includes prior mod binaries for dependencies; all 269
current production source files are supplied explicitly, and the complete 632
output classes are checked against the reference rather than copied from it.
