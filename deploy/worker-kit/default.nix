let
  nixpkgsLock = builtins.fromJSON (builtins.readFile ./nixpkgs.json);
  pinnedNixpkgs = builtins.fetchTarball {
    inherit (nixpkgsLock) url sha256;
  };
in
{ pkgs ? import pinnedNixpkgs {} }:

let
  codegraphPlatformPackage =
    if pkgs.stdenv.hostPlatform.isAarch64
    then "@colbymchenry/codegraph-linux-arm64"
    else "@colbymchenry/codegraph-linux-x64";
  claudeCli = pkgs.stdenvNoCC.mkDerivation {
    pname = "claude-code-cli";
    version = "2.1.197";
    src = ./claude;
    dontUnpack = true;
    # Claude is a standalone executable with an appended payload; stripping leaves only Bun.
    dontStrip = true;
    nativeBuildInputs = [ pkgs.autoPatchelfHook ];
    buildInputs = [
      pkgs.stdenv.cc.cc.lib
      pkgs.zlib
    ];
    installPhase = ''
      mkdir -p $out/bin
      install -m 755 $src $out/bin/claude
    '';
  };
  nodeTools = pkgs.buildNpmPackage {
    pname = "codify-worker-kit-node-tools";
    version = "0.1.0";
    src = ./npm;
    npmDepsHash = "sha256-gj677HBaLczVrzMxv+2SaRgkKMCRrTpktpVxUftHOpc=";
    dontNpmBuild = true;
    installPhase = ''
      runHook preInstall
      mkdir -p $out/lib/codify-node-tools
      cp -R node_modules $out/lib/codify-node-tools/
      rm -f $out/lib/codify-node-tools/node_modules/${codegraphPlatformPackage}/node
      cp ${./validate_mermaid_summary.mjs} \
        $out/lib/codify-node-tools/validate_mermaid_summary.mjs
      runHook postInstall
    '';
  };
in
pkgs.symlinkJoin {
  name = "codify-worker-kit-runtime";
  passthru = {
    nixpkgsRevision = nixpkgsLock.rev;
    nixpkgsVersion = pkgs.lib.version;
  };
  paths = [
    pkgs.bashInteractive
    pkgs.cacert
    pkgs.coreutils
    pkgs.curl
    pkgs.findutils
    pkgs.gawk
    pkgs.git
    pkgs.gnugrep
    pkgs.gnused
    pkgs.gnutar
    pkgs.gzip
    pkgs.jq
    pkgs.nodejs_22
    pkgs.openssh
    pkgs.python312
    pkgs.ripgrep
    pkgs.which
    claudeCli
    nodeTools
  ];
  nativeBuildInputs = [ pkgs.makeWrapper ];
  postBuild = ''
    rm -f $out/bin/codegraph
    makeWrapper ${pkgs.nodejs_22}/bin/node $out/bin/codegraph \
      --add-flags "$out/lib/codify-node-tools/node_modules/${codegraphPlatformPackage}/lib/dist/bin/codegraph.js"
    makeWrapper ${pkgs.nodejs_22}/bin/node $out/bin/codify-validate-mermaid \
      --add-flags "$out/lib/codify-node-tools/validate_mermaid_summary.mjs"
  '';
}
