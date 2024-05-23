import { useContext } from 'react';

import { ElectronApiContext } from '@/context/ElectronApiProvider';

export const useElectronApi = () => {
  const { setAppHeight, closeApp, minimizeApp, showNotification } =
    useContext(ElectronApiContext);

  return {
    setAppHeight,
    closeApp,
    minimizeApp,
    showNotification,
  };
};
