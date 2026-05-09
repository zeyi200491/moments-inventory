import { Component, type ErrorInfo, type ReactNode } from "react";

type ErrorBoundaryProps = {
  children: ReactNode;
};

type ErrorBoundaryState = {
  hasError: boolean;
};

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = {
    hasError: false,
  };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Workbench render error", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="shell">
          <section className="panel panel-soft">
            <div className="panel-heading">
              <span className="eyebrow">Application Error</span>
              <h2>页面加载失败</h2>
            </div>
            <div className="error-box" role="alert">
              组件渲染时发生错误，请刷新页面后重试。
            </div>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}
