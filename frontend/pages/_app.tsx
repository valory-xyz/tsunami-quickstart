import '../styles/globals.scss';

import { ConfigProvider } from 'antd';
import type { AppProps } from 'next/app';
import { useEffect, useRef } from 'react';

import { Layout } from '@/components/Layout';
import {
  AppInfoProvider,
  PageStateProvider,
  ServicesProvider,
  SetupProvider,
} from '@/context';
import { BalanceProvider } from '@/context/BalanceProvider';
import { ElectronApiProvider } from '@/context/ElectronApiProvider';
import { MasterSafeProvider } from '@/context/MasterSafeProvider';
import { RewardProvider } from '@/context/RewardProvider';
import { SettingsProvider } from '@/context/SettingsProvider';
import { WalletProvider } from '@/context/WalletProvider';
import { mainTheme } from '@/theme';

export default function App({ Component, pageProps }: AppProps) {
  const isMounted = useRef(false);

  useEffect(() => {
    isMounted.current = true;
    return () => {
      isMounted.current = false;
    };
  }, []);

  return (
    <AppInfoProvider>
      <PageStateProvider>
        <WalletProvider>
          <MasterSafeProvider>
            <ServicesProvider>
              <RewardProvider>
                <BalanceProvider>
                  <SetupProvider>
                    <SettingsProvider>
                      {isMounted ? (
                        <ConfigProvider theme={mainTheme}>
                          <ElectronApiProvider>
                            <Layout>
                              <Component {...pageProps} />
                            </Layout>
                          </ElectronApiProvider>
                        </ConfigProvider>
                      ) : null}
                    </SettingsProvider>
                  </SetupProvider>
                </BalanceProvider>
              </RewardProvider>
            </ServicesProvider>
          </MasterSafeProvider>
        </WalletProvider>
      </PageStateProvider>
    </AppInfoProvider>
  );
}
