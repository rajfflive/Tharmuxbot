import { Switch, Route, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "@/pages/not-found";
import { useDarkMode } from "@/hooks/use-dark-mode";
import { Layout } from "@/components/layout";
import { AuthProvider, useAuth } from "@/contexts/auth-context";

import DashboardPage from "@/pages/dashboard";
import ServicesPage from "@/pages/services";
import ServiceNewPage from "@/pages/service-new";
import ServiceDetailPage from "@/pages/service-detail";
import LoginPage from "@/pages/login";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        const status = (error as { status?: number })?.status;
        if (status === 401 || status === 403 || status === 404) return false;
        return failureCount < 2;
      },
    },
  },
});

function AuthGate() {
  const { authenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-muted-foreground text-sm">Loading...</div>
      </div>
    );
  }

  if (!authenticated) {
    return <LoginPage />;
  }

  return (
    <Layout>
      <Switch>
        <Route path="/" component={DashboardPage} />
        <Route path="/services" component={ServicesPage} />
        <Route path="/services/new" component={ServiceNewPage} />
        <Route path="/services/:id" component={ServiceDetailPage} />
        <Route component={NotFound} />
      </Switch>
    </Layout>
  );
}

function App() {
  useDarkMode();
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, "")}>
          <AuthProvider>
            <AuthGate />
          </AuthProvider>
        </WouterRouter>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;
