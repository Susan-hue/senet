import type { CSSProperties } from "react";

const layer = (z: number): CSSProperties => ({
  position: "absolute",
  top: "50%",
  left: "50%",
  transform: `translate(-50%,-50%) translateZ(${z}px)`,
});

const bar = (
  left: number,
  top: number,
  width: number,
  height: number,
  background: string,
): CSSProperties => ({
  position: "absolute",
  left,
  top,
  width,
  height,
  borderRadius: 99,
  background,
});

const scene: CSSProperties = {
  position: "relative",
  width: "100%",
  height: "100%",
  transformStyle: "preserve-3d",
  transform: "rotateX(58deg) rotateZ(-42deg)",
  animation: "floatScene 9s ease-in-out infinite",
};

export function IsometricStack({ variant = "desktop" }: { variant?: "desktop" | "compact" }) {
  if (variant === "compact") {
    return (
      <div style={{ width: 170, height: 128, perspective: 1100 }}>
        <div style={scene}>
          <div
            style={{
              ...layer(6),
              width: 150,
              height: 106,
              borderRadius: 14,
              background: "linear-gradient(135deg, rgba(99,102,241,0.16), rgba(139,92,246,0.05))",
              border: "1px solid rgba(124,108,246,0.45)",
              boxShadow: "0 0 30px rgba(99,102,241,0.28), inset 0 1px 0 rgba(255,255,255,0.1)",
            }}
          />
          <div
            style={{
              ...layer(46),
              width: 150,
              height: 106,
              borderRadius: 14,
              background: "linear-gradient(135deg, rgba(99,102,241,0.2), rgba(139,92,246,0.06))",
              border: "1px solid rgba(124,108,246,0.55)",
              boxShadow: "0 0 34px rgba(99,102,241,0.32), inset 0 1px 0 rgba(255,255,255,0.12)",
            }}
          >
            <div style={bar(16, 16, 28, 5, "rgba(165,160,255,0.7)")} />
            <div style={bar(16, 29, 96, 4, "rgba(255,255,255,0.14)")} />
          </div>
          <div
            style={{
              ...layer(88),
              width: 150,
              height: 106,
              borderRadius: 14,
              background: "linear-gradient(135deg, rgba(124,108,246,0.32), rgba(139,92,246,0.12))",
              border: "1px solid rgba(165,160,255,0.7)",
              boxShadow: "0 0 46px rgba(124,108,246,0.5), inset 0 1px 0 rgba(255,255,255,0.18)",
            }}
          >
            <div style={{ ...bar(16, 16, 38, 6, "#fff"), opacity: 0.9 }} />
            <div style={bar(16, 30, 110, 4, "rgba(255,255,255,0.2)")} />
          </div>
          <div
            style={{
              ...layer(104),
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: "#C7C2FF",
              boxShadow: "0 0 18px 3px rgba(165,160,255,0.9)",
              animation: "glowPulse 2.4s ease-in-out infinite",
            }}
          />
        </div>
      </div>
    );
  }

  return (
    <div style={{ width: 380, height: 380, perspective: 1500 }}>
      <div style={scene}>
        <div
          style={{
            ...layer(-50),
            width: 300,
            height: 300,
            backgroundImage:
              "linear-gradient(rgba(124,108,246,0.22) 1px,transparent 1px),linear-gradient(90deg,rgba(124,108,246,0.22) 1px,transparent 1px)",
            backgroundSize: "30px 30px",
            border: "1px solid rgba(124,108,246,0.22)",
            boxShadow: "0 0 60px rgba(99,102,241,0.25)",
          }}
        />
        <div
          style={{
            ...layer(8),
            width: 230,
            height: 168,
            borderRadius: 18,
            background: "linear-gradient(135deg, rgba(99,102,241,0.14), rgba(139,92,246,0.04))",
            border: "1px solid rgba(124,108,246,0.4)",
            boxShadow: "0 0 34px rgba(99,102,241,0.22), inset 0 1px 0 rgba(255,255,255,0.1)",
          }}
        />
        <div
          style={{
            ...layer(54),
            width: 230,
            height: 168,
            borderRadius: 18,
            background: "linear-gradient(135deg, rgba(99,102,241,0.18), rgba(139,92,246,0.05))",
            border: "1px solid rgba(124,108,246,0.5)",
            boxShadow: "0 0 38px rgba(99,102,241,0.3), inset 0 1px 0 rgba(255,255,255,0.12)",
          }}
        >
          <div style={bar(20, 22, 34, 6, "rgba(165,160,255,0.6)")} />
          <div style={bar(20, 38, 120, 5, "rgba(255,255,255,0.12)")} />
        </div>
        <div
          style={{
            ...layer(100),
            width: 230,
            height: 168,
            borderRadius: 18,
            background: "linear-gradient(135deg, rgba(99,102,241,0.22), rgba(139,92,246,0.06))",
            border: "1px solid rgba(124,108,246,0.6)",
            boxShadow: "0 0 44px rgba(99,102,241,0.36), inset 0 1px 0 rgba(255,255,255,0.14)",
          }}
        >
          <div style={bar(20, 22, 34, 6, "rgba(165,160,255,0.75)")} />
          <div style={bar(20, 38, 150, 5, "rgba(255,255,255,0.16)")} />
          <div style={bar(20, 52, 96, 5, "rgba(255,255,255,0.1)")} />
        </div>
        <div
          style={{
            ...layer(150),
            width: 230,
            height: 168,
            borderRadius: 18,
            background: "linear-gradient(135deg, rgba(124,108,246,0.32), rgba(139,92,246,0.12))",
            border: "1px solid rgba(165,160,255,0.7)",
            boxShadow: "0 0 60px rgba(124,108,246,0.5), inset 0 1px 0 rgba(255,255,255,0.2)",
          }}
        >
          <div style={{ ...bar(20, 22, 46, 7, "#fff"), opacity: 0.9 }} />
          <div style={bar(20, 40, 160, 5, "rgba(255,255,255,0.2)")} />
        </div>
        <div
          style={{
            ...layer(170),
            width: 12,
            height: 12,
            borderRadius: "50%",
            background: "#C7C2FF",
            boxShadow: "0 0 22px 4px rgba(165,160,255,0.9)",
            animation: "glowPulse 2.4s ease-in-out infinite",
          }}
        />
      </div>
    </div>
  );
}
