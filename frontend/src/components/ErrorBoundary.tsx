import { Component, type ErrorInfo, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";

interface ErrorBoundaryState {
  hasError: boolean;
}

export class ErrorBoundary extends Component<
  { children: ReactNode },
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("界面渲染出错", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="render-error" role="alert">
          <h1>界面渲染出错</h1>
          <p>工作区数据仍保留。</p>
          <button
            className="button button-primary"
            onClick={() => window.location.reload()}
          >
            <RefreshCw size={15} />
            重新加载
          </button>
        </main>
      );
    }
    return this.props.children;
  }
}
